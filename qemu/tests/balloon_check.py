import time
import re
import logging
import random

from avocado.core import exceptions

from virttest import qemu_monitor
from virttest import utils_test
from virttest import utils_misc
from virttest import error_context
from virttest.utils_test.qemu import MemoryBaseTest


class BallooningTest(MemoryBaseTest):

    """
    Provide basic functions for memory ballooning test cases
    """

    def __init__(self, test, params, env):
        self.test_round = 0
        super(BallooningTest, self).__init__(test, params, env)

        self.vm = env.get_vm(params["main_vm"])
        if params.get("paused_after_start_vm") != "yes":
            self.params["balloon_test_setup_ready"] = False
            if self.params.get('os_type') == 'windows':
                sleep_time = 180
            else:
                sleep_time = 90
            logging.info("Waiting %d seconds for guest's "
                         "applications up" % sleep_time)
            time.sleep(sleep_time)
            self.params["balloon_test_setup_ready"] = True
            self.ori_gmem = self.get_memory_status()
            self.current_gmem = self.ori_gmem
        self.ori_mem = self.get_vm_mem(self.vm)
        self.current_mmem = self.get_ballooned_memory()
        if self.current_mmem != self.ori_mem:
            self.balloon_memory(self.ori_mem)
        self.current_mmem = self.ori_mem

    def get_ballooned_memory(self):
        """
        Get the size of memory from monitor

        :return: the size of memory
        :rtype: int
        """
        try:
            output = self.vm.monitor.info("balloon")
            ballooned_mem = int(re.findall(r"\d+", str(output))[0])
            if self.vm.monitor.protocol == "qmp":
                ballooned_mem = ballooned_mem / (1024 ** 2)
        except qemu_monitor.MonitorError as emsg:
            logging.error(emsg)
            return 0
        return ballooned_mem

    @error_context.context_aware
    def memory_check(self, step, ballooned_mem):
        """
        Check memory status according expect values

        :param step: the check point string
        :type step: string
        :param ballooned_mem: ballooned memory in current step
        :type ballooned_mem: int
        :return: memory size get from monitor and guest
        :rtype: tuple
        """
        error_context.context("Check memory status %s" % step, logging.info)
        mmem = self.get_ballooned_memory()
        gmem = self.get_memory_status()
        gcompare_threshold = int(self.params.get("guest_compare_threshold", 100))
        # for windows illegal test:set windows guest balloon in (1,100),free memory will less than 50M
        if ballooned_mem >= self.ori_mem - 100:
            timeout = float(self.params.get("login_timeout", 600))
            session = self.vm.wait_for_login(timeout=timeout)
            try:
                if self.get_win_mon_free_mem(session) > 50:
                    self.test.fail("Balloon_min test failed %s" % step)
            finally:
                session.close()
        else:
            guest_ballooned_mem = abs(gmem - self.ori_gmem)
            if (abs(mmem - self.ori_mem) != ballooned_mem or
                    (abs(guest_ballooned_mem - ballooned_mem) > gcompare_threshold)):
                self.error_report(step, self.ori_mem - ballooned_mem, mmem, gmem)
                raise exceptions.TestFail("Balloon test failed %s" % step)
        return (mmem, gmem)

    @error_context.context_aware
    def balloon_memory(self, new_mem):
        """
        Baloon memory to new_mem and verifies on both qemu monitor and
        guest OS if change worked.

        :param new_mem: New desired memory.
        :type new_mem: int
        """
        self.env["balloon_test"] = 0
        error_context.context("Change VM memory to %s" % new_mem, logging.info)
        try:
            self.vm.balloon(new_mem)
            self.env["balloon_test"] = 1
        except Exception as e:
            if self.params.get('illegal_value_check', 'no') == 'no' and new_mem != self.get_ballooned_memory():
                raise exceptions.TestFail("Balloon memory fail with error"
                                          " message: %s" % e)
        if new_mem > self.ori_mem:
            compare_mem = self.ori_mem
        elif new_mem == 0:
            compare_mem = self.current_mmem
        elif new_mem <= 100:
            self._balloon_post_action()
            self.current_mmem = self.get_ballooned_memory()
            compare_mem = self.current_mmem
        else:
            compare_mem = new_mem

        balloon_timeout = float(self.params.get("balloon_timeout", 240))
        status = utils_misc.wait_for((lambda: compare_mem ==
                                      self.get_ballooned_memory()),
                                     balloon_timeout)
        if status is None:
            raise exceptions.TestFail("Failed to balloon memory to expect"
                                      " value during %ss" % balloon_timeout)

    def run_balloon_sub_test(self, test, params, env, test_tag):
        """
        Run subtest after ballooned memory. Set up the related parameters
        according to the subtest.

        :param test: QEMU test object
        :type test: object
        :param params: Dictionary with the test parameters
        :type param: dict
        :param env: Dictionary with test environment.
        :type env: dict
        :return: if qemu-kvm process quit after test. There are three status
                 for this variable. -1 means the process will not quit. 0
                 means the process will quit but already restart in sub test.
                 1 means the process quit after sub test.
        :rtype: int
        """
        utils_test.run_virt_sub_test(test, params, env,
                                     sub_type=test_tag)
        qemu_quit_after_test = -1
        if "shutdown" in test_tag:
            logging.info("Guest shutdown normally after balloon")
            qemu_quit_after_test = 1
        if params.get("session_need_update", "no") == "yes":
            self.session = self.get_session(self.vm)
        if params.get("qemu_quit_after_sub_case", "no") == "yes":
            self.current_mmem = self.ori_mem
            self.current_gmem = self.ori_gmem
            qemu_quit_after_test = 0
        return qemu_quit_after_test

    def _mem_state(self, threshold):
        """
        A generator to get guest memory until it does not change
        """
        stable = False
        ori_mem = self.get_memory_status()
        while True:
            yield stable
            cur_mem = self.get_memory_status()
            stable = abs(cur_mem - ori_mem) < threshold
            ori_mem = cur_mem

    def wait_for_balloon_complete(self, timeout):
        """
        Wait until guest memory don't change
        """
        logging.info("Wait until guest memory don't change")
        threshold = int(self.params.get("guest_stable_threshold", 100))
        is_stable = self._mem_state(threshold)
        utils_misc.wait_for(lambda: next(is_stable), timeout,
                            step=float(self.params.get("guest_check_step", 10.0)))

    def get_memory_boundary(self, balloon_type=''):
        """
        Get the legal memory boundary for balloon operation.

        :param balloon_type: evict or enlarge
        :type balloon_type: string
        :return: min and max size of the memory
        :rtype: tuple
        """
        max_size = self.ori_mem
        min_size = self.params.get("minmem", "512M")
        min_size = int(float(utils_misc.normalize_data_size(min_size)))
        balloon_buffer = self.params.get("balloon_buffer", 300)
        if self.params.get('os_type') == 'windows':
            logging.info("Get windows miminum balloon value:")
            self.vm.balloon(1)
            balloon_timeout = self.params.get("balloon_timeout", 900)
            self.wait_for_balloon_complete(balloon_timeout)
            used_size = min((self.get_ballooned_memory() + balloon_buffer), max_size)
            self.vm.balloon(max_size)
            self.wait_for_balloon_complete(balloon_timeout)
            self.ori_gmem = self.get_memory_status()
        else:
            vm_total = self.get_memory_status()
            vm_mem_free = self.get_free_mem()
            used_size = min((self.ori_mem - vm_mem_free + balloon_buffer), max_size)
        if balloon_type == "enlarge":
            min_size = self.current_mmem
        elif balloon_type == "evict":
            max_size = self.current_mmem
        min_size = max(used_size, min_size)
        return min_size, max_size

    @error_context.context_aware
    def run_ballooning_test(self, expect_mem, tag):
        """
        Run a loop of ballooning test

        :param expect_mem: memory will be setted in test
        :type expect_mem: int
        :param tag: test tag to get related params
        :type tag: string
        :return: If test should quit after test
        :rtype: bool
        """
        def _memory_check_after_sub_test():
            try:
                output = self.memory_check("after subtest", ballooned_mem)
            except exceptions.TestFail:
                return None
            return output

        if self.test_round < 1:
            self.memory_check("before ballooning test", 0)

        params_tag = self.params.object_params(tag)
        self.balloon_memory(expect_mem)
        self.test_round += 1
        ballooned_memory = self.ori_mem - expect_mem
        if ballooned_memory < 0 or ballooned_memory == self.ori_mem:
            ballooned_memory = 0
        mmem, gmem = self.memory_check("after %s memory" % tag, ballooned_memory)
        self.current_mmem = mmem
        self.current_gmem = gmem
        if (params_tag.get("run_sub_test_after_balloon", "no") == "yes" and
                params_tag.get('sub_test_after_balloon')):
            sub_type = params_tag['sub_test_after_balloon']
            should_quit = self.run_balloon_sub_test(self.test, params_tag,
                                                    self.env, sub_type)
            if should_quit == 1:
                return True

            elif should_quit == 0:
                expect_mem = self.ori_mem

            sleep_before_check = int(self.params.get("sleep_before_check", 0))
            timeout = int(self.params.get("balloon_timeout", 100)) + sleep_before_check
            ballooned_mem = abs(self.ori_mem - expect_mem)
            msg = "Wait memory balloon back after "
            msg += params_tag['sub_test_after_balloon']
            ret = utils_misc.wait_for(_memory_check_after_sub_test,
                                      timeout, sleep_before_check, 5, msg)
            if not ret:
                self.test.fail("After sub test, memory check failed")
            self.current_mmem = ret[0]
            self.current_gmem = ret[1]
        return False

    def reset_memory(self):
        """
        Reset memory to original value
        """
        if self.vm.is_alive():
            self.balloon_memory(self.ori_mem)

    def get_free_mem(self):
        """
        Report free memory detect by OS.
        """
        return self.get_guest_free_mem(self.vm)

    def get_used_mem(self):
        """
        Report used memory detect by OS.
        """
        return self.get_guest_used_mem(self.vm)

    def get_total_mem(self):
        """
        Report total memory detect by OS.
        """
        return self.get_guest_total_mem(self.vm)

    def error_report(self, step, expect_value, monitor_value, guest_value):
        """
        Generate the error report

        :param step: the step of the error happen
        :param expect_value: memory size assign to the vm
        :param monitor_value: memory size report from monitor, this value can
                              be None
        :param guest_value: memory size report from guest, this value can be
                            None
        """
        pass

    def get_memory_status(self):
        """
        Get Memory status inside guest.
        """
        pass

    def _balloon_post_action(self):
        """
        Wait for guest memory goes into stable status
        """
        pass


class BallooningTestWin(BallooningTest):

    """
    Windows memory ballooning test
    """
    def _balloon_post_action(self):
        """
        Wait for guest memory goes into stable status
        """
        balloon_timeout = float(self.params.get("balloon_timeout", 240))
        self.wait_for_balloon_complete(balloon_timeout)

    def error_report(self, step, expect_value, monitor_value, guest_value):
        """
        Generate the error report

        :param step: the step of the error happen
        :param expect_value: memory size assign to the vm
        :param monitor_value: memory size report from monitor, this value can
                              be None
        :param guest_value: memory size report from guest, this value can be
                            None
        """
        logging.error("Memory size mismatch %s:\n" % step)
        error_msg = "Wanted to be changed: %s\n" % abs(self.ori_mem -
                                                       expect_value)
        if monitor_value:
            error_msg += "Changed in monitor: %s\n" % abs(self.ori_mem -
                                                          monitor_value)
        error_msg += "Changed in guest: %s\n" % abs(
            guest_value - self.ori_gmem)
        logging.error(error_msg)

    def get_memory_status(self):
        """
        Get Memory status inside guest.

        :return: the used memory size inside guest.
        :rtype: int
        """
        return int(self.get_used_mem())

    def get_win_mon_free_mem(self, session):
        """
        Get Performance Monitored Free memory.

        :param session: shell Object
        :return string: freespace M-bytes
        """
        cmd = r'typeperf "\Memory\Free & Zero Page List Bytes" -sc 1'
        status, output = session.cmd_status_output(cmd)
        if status == 0:
            free = "%s" % re.findall(r"\d+\.\d+", output)[2]
            free = float(utils_misc.normalize_data_size(free, order_magnitude="M"))
            return int(free)
        else:
            self.test.fail("Failed to get windows guest free memory")

    def get_disk_vol(self, session):
        """
        Get virtio-win disk volume letter for windows guest.

        :param session: VM session.
        """
        key = "VolumeName like 'virtio-win%'"
        try:
            return utils_misc.get_win_disk_vol(session,
                                               condition=key)
        except Exception:
            self.test.error("Could not get virtio-win disk vol!")

    @error_context.context_aware
    def operate_balloon_service(self, session, operation):
        """
        Run/check/stop/install/uninstall balloon service in windows guest

        :param session: shell Object
        :param operation: operation against balloon serive, e.g. run/status/
                          uninstall/stop
        :return: cmd execution output
        """
        error_context.context("%s Balloon Service in guest." % operation,
                              logging.info)
        drive_letter = self.get_disk_vol(session)
        try:
            operate_cmd = self.params["%s_balloon_service"
                                      % operation] % drive_letter
            if operation == "status":
                output = session.cmd_output(operate_cmd)
            else:
                output = session.cmd(operate_cmd)
        except Exception as err:
            self.test.error("%s balloon service failed! Error msg is:\n%s"
                            % (operation, err))
        return output

    @error_context.context_aware
    def configure_balloon_service(self, session):
        """
        Check balloon service and install it if it's not running.

        :param session: shell Object
        :param operation: operation against balloon serive, e.g. run/status/
                          uninstall/stop
        """
        error_context.context("Check Balloon Service status before install"
                              "service", logging.info)
        output = self.operate_balloon_service(session, "status")
        if re.search("running", output.lower(), re.M):
            logging.info("Balloon service is already running !")
        elif re.search("stop", output.lower(), re.M):
            logging.info("Balloon service is stopped,start it now")
            self.operate_balloon_service(session, "run")
        else:
            logging.info("Install Balloon Service in guest.")
            self.operate_balloon_service(session, "install")


class BallooningTestLinux(BallooningTest):

    """
    Linux memory ballooning test
    """

    def error_report(self, step, expect_value, monitor_value, guest_value):
        """
        Generate the error report

        @param step: the step of the error happen
        @param expect_value: memory size assign to the vm
        @param monitor_value: memory size report from monitor, this value can
                              be None
        @param guest_value: memory size report from guest, this value can be
                            None
        """
        logging.error("Memory size mismatch %s:\n" % step)
        error_msg = "Assigner to VM: %s\n" % expect_value
        if monitor_value:
            error_msg += "Reported by monitor: %s\n" % monitor_value
        if guest_value:
            error_msg += "Reported by guest OS: %s\n" % guest_value
        logging.error(error_msg)

    def get_memory_status(self):
        """
        Get Memory status inside guest.
        """
        if self.params.get("balloon_opt_deflate_on_oom") == "yes":
            return int(self.get_used_mem())
        return int(self.get_total_mem())


@error_context.context_aware
def run(test, params, env):
    """
    Check Memory ballooning, use M when compare memory in this script:
    1) Boot a guest with balloon enabled.
    2) Balloon guest memory to given value and run sub test(Optional)
    3) Repeat step 2 following the cfg files.
    8) Reset memory back to the original value

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    if params['os_type'] == 'windows':
        balloon_test = BallooningTestWin(test, params, env)
    else:
        balloon_test = BallooningTestLinux(test, params, env)

    if params.get("balloon_opt_deflate_on_oom") == "yes":
        guest_ori_mem = balloon_test.get_total_mem()

    for tag in params.objects('test_tags'):
        error_context.context("Running %s test" % tag, logging.info)
        params_tag = params.object_params(tag)
        if params_tag.get('expect_memory'):
            expect_mem = int(params_tag.get('expect_memory'))
        elif params_tag.get('expect_memory_ratio'):
            expect_mem = int(balloon_test.ori_mem *
                             float(params_tag.get('expect_memory_ratio')))
        #set evict illegal value to "0" for both linux and windows
        elif params_tag.get('illegal_value_check', 'no') == 'yes':
            if tag == 'evict':
                expect_mem = 0
            else:
                expect_mem = int(balloon_test.ori_mem+random.uniform(1, 1000))
        else:
            balloon_type = params_tag['balloon_type']
            min_sz, max_sz = balloon_test.get_memory_boundary(balloon_type)
            expect_mem = int(random.uniform(min_sz, max_sz))
            if params_tag.get('minimum_value_check', 'no') == 'yes':
                expect_mem = int(min_sz)

        quit_after_test = balloon_test.run_ballooning_test(expect_mem, tag)
        if params.get("balloon_opt_deflate_on_oom") == "yes":
            guest_curr_mem = balloon_test.get_total_mem()
            if guest_ori_mem != guest_curr_mem:
                balloon_test.error_report("after %s memory" % tag,
                                          expect_value=guest_ori_mem,
                                          guest_value=guest_curr_mem)
                test.fail("Balloon test failed %s" % tag)
        if quit_after_test:
            return
    try:
        balloon_test.reset_memory()
    finally:
        balloon_test.close_sessions()
