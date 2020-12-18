import re
import os
import signal
import logging
import time

from avocado.utils import process
from virttest import utils_misc
from virttest import utils_test
from virttest import error_context
from virttest import qemu_migration

from virttest.qemu_capabilities import Flags
from virttest.utils_numeric import normalize_data_size

from qemu.tests import virtio_serial_file_transfer
from qemu.tests.timedrift_no_net import subw_guest_pause_resume  # pylint: disable=W0611


@error_context.context_aware
def reboot_guest(test, params, vm, session):
    """
    Reboot guest from system_reset or shell.
    """

    vm.reboot(session, method=params["reboot_method"])


@error_context.context_aware
def shutdown_guest(test, params, vm, session):
    """
    Shutdown guest via system_powerdown or shell.
    """

    if params.get("shutdown_method") == "shell":
        session.sendline(params["shutdown_command"])
    elif params.get("shutdown_method") == "system_powerdown":
        vm.monitor.system_powerdown()
    if not vm.wait_for_shutdown(int(params.get("shutdown_timeout", 360))):
        test.fail("guest refuses to go down")


@error_context.context_aware
def live_migration_guest(test, params, vm, session):
    """
    Run migrate_set_speed, then migrate guest.
    """

    mig_speed = params.get("mig_speed", "1G")
    if vm.check_capability(Flags.MIGRATION_PARAMS):
        qemu_migration.set_migrate_parameter_max_bandwidth(
                vm, int(normalize_data_size(mig_speed, 'B')))
    else:
        vm.monitor.migrate_set_speed(mig_speed)
    vm.migrate()


@error_context.context_aware
def vcpu_hotplug_guest(test, params, vm, session):
    """
    Vcpu hot plug test.
    """

    maxcpus = int(params["vcpu_maxcpus"])
    current_cpus = int(params.get("smp", 2))
    for cpuid in range(current_cpus, maxcpus):
        error_context.context("hot-pluging vCPU %s" % cpuid, logging.info)
        vm.hotplug_vcpu(cpu_id=cpuid)
        # make the cpu hotplug has slot during data transfer
        time.sleep(2)


@error_context.context_aware
def kill_host_serial_pid(params, vm):
    """
    Kill serial script process on host to avoid two threads run
    simultaneously.
    """
    port_path = virtio_serial_file_transfer.get_virtio_port_property(
            vm, params["file_transfer_serial_port"])[1]

    host_process = 'ps aux | grep "serial_host_send_receive.py"'
    host_process = process.system_output(host_process,
                                         shell=True).decode()
    host_process = re.findall(r'(.*?)%s(.*?)\n' % port_path, host_process)
    if host_process:
        host_process = str(host_process[0]).split()[1]
        logging.info("Kill previous serial process on host")
        os.kill(int(host_process), signal.SIGINT)


def run_bg_test(test, params, vm, sender="both"):
    """
    Run serial data transfer backgroud test.

    :return: return the background case thread if it's successful;
             else raise error.
    """

    # import driver_in_use in this function to avoid circular imports
    from qemu.tests import driver_in_use

    error_context.context("Run serial transfer test in background",
                          logging.info)
    stress_thread = utils_misc.InterruptedThread(
            virtio_serial_file_transfer.transfer_data, (params, vm),
            {"sender": sender})
    stress_thread.start()

    check_bg_timeout = float(params.get('check_bg_timeout', 120))
    if not utils_misc.wait_for(lambda: driver_in_use.check_bg_running(vm,
                               params), check_bg_timeout, 0, 1):
        test.fail("Backgroud test is not alive!")
    return stress_thread


@error_context.context_aware
def run(test, params, env):
    """
    Driver in use test:
    1) boot guest with serial device.
    2) Transfer data between host and guest via serialport.
    3) run interrupt test during background stress test.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    driver = params["driver_name"]
    sender = params['file_sender']
    timeout = int(params.get("login_timeout", 360))
    suppress_exception = params.get("suppress_exception", "no") == "yes"

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    if params["os_type"] == "windows":
        session = utils_test.qemu.windrv_check_running_verifier(session, vm,
                                                                test, driver,
                                                                timeout)

    bg_thread = run_bg_test(test, params, vm, sender)
    globals().get(params["interrupt_test"])(test, params, vm, session)

    # for vcpu hotplug subtest, only check guest crash.
    vcpu_hotplug = params.get_boolean("vcpu_hotplug")
    if vcpu_hotplug:
        error_context.context("Check if guest is alive.", logging.info)
        vm.verify_kernel_crash()
        session = vm.wait_for_login(timeout=timeout)
        session.close()
        return

    if bg_thread:
        bg_thread.join(timeout=timeout,
                       suppress_exception=suppress_exception)
    if vm.is_alive():
        kill_host_serial_pid(params, vm)
        if (virtio_serial_file_transfer.transfer_data(
                params, vm, sender=sender) is not True):
            test.fail("Serial data transfter test failed.")
