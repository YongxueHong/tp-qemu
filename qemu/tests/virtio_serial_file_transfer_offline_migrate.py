import os
import logging

from virttest import utils_test
from virttest import utils_misc
from virttest import error_context
from virttest import qemu_migration
from virttest.qemu_capabilities import Flags
from virttest.utils_numeric import normalize_data_size
from qemu.tests.virtio_serial_file_transfer import transfer_data


@error_context.context_aware
def run(test, params, env):
    """
    Offline migration with virtio-serial enabled.

     1) Start guest with virtio serial device vs1 & vs2.
     2) Transfer data via vs1 on the source guest.
     3) Offline migration.
     4) Transfer data via vs2 with the destination guest:

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def run_serial_data_transfer():
        """
        Transfer data between two ports.
        """

        for port in params.objects("serials"):
            port_params = params.object_params(port)
            if not port_params['serial_type'].startswith('virt'):
                continue
            params['file_transfer_serial_port'] = port
            transfer_data(params, vm)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    if params["os_type"] == "windows":
        session = vm.wait_for_login()
        driver_name = params["driver_name"]
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name)
        session.close()
    error_context.context("transferring data on source guest", logging.info)
    run_serial_data_transfer()
    mig_protocol = params.get("migration_protocol", "tcp")
    mig_exec_cmd_src = params.get("migration_exec_cmd_src")
    mig_exec_cmd_dst = params.get("migration_exec_cmd_dst")
    mig_exec_file = params.get("migration_exec_file", "/var/tmp/exec")
    mig_exec_file += "-%s" % utils_misc.generate_random_string(8)
    mig_exec_cmd_src = mig_exec_cmd_src % mig_exec_file
    mig_exec_cmd_dst = mig_exec_cmd_dst % mig_exec_file

    mig_speed = params.get("mig_speed", "1G")
    if vm.check_capability(Flags.MIGRATION_PARAMS):
        qemu_migration.set_migrate_parameter_max_bandwidth(
                vm, int(normalize_data_size(mig_speed, 'B')))
    else:
        vm.monitor.migrate_set_speed(mig_speed)
    try:
        vm.migrate(protocol=mig_protocol, offline=True,
                   migration_exec_cmd_src=mig_exec_cmd_src,
                   migration_exec_cmd_dst=mig_exec_cmd_dst)
        error_context.context("transferring data on destination guest",
                              logging.info)
        run_serial_data_transfer()
        vm.verify_kernel_crash()
    finally:
        os.remove(mig_exec_file)
