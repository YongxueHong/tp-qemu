import logging

from virttest import error_context
from virttest.qemu_devices import qdevices
from virttest import env_process
import time

@error_context.context_aware
def run(test, params, env):

    def _block_hotplug(vm, image_name):
        """
        Hotplug disks and verify it in qtree
        """
        image_params = params.object_params(image_name)
        devs = vm.devices.images_define_by_params(image_name,
                                                  image_params)
        for dev in devs:
            logging.info('****************hot plug %s*****************' % dev)
            ret = vm.devices.simple_hotplug(dev, vm.monitor)
            if ret[1] is False:
                test.fail("Failed to hotplug device '%s'."
                          "Output:\n%s" % (dev, ret[0]))
        devs = [dev for dev in devs if not isinstance(dev, qdevices.QHPBlockdev)]
        return devs

    def _block_unplug(vm, device_list):
        """
        Unplug disks and verify it in qtree
        """
        for dev in reversed(device_list):
            logging.info('****************hot unplug %s*****************' % dev)
            ret = vm.devices.simple_unplug(dev, vm.monitor)
            if ret[1] is False:
                test.fail("Failed to unplug device '%s'."
                          "Ouptut:\n%s" % (dev, ret[0]))

    params['start_vm'] = 'yes'
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])

    for i in range(0, 5):
        # image_tag = "stg%s" % extra_image
        # params["images"] += " %s" % image_tag
        # params["image_name_%s" % image_tag] = "images/%s" % image_tag
        # params["image_size_%s" % image_tag] = extra_image_size
        # params["force_create_image_%s" % image_tag] = "yes"
        # image_params = params.object_params(image_tag)
        image_tag = 'hpstg%s' % i
        image_params = params.object_params(image_tag)
        env_process.preprocess_image(test, image_params, image_tag)

    for i in range(0, 5):
        dev = _block_hotplug(vm, 'hpstg%s' % i)
        time.sleep(3)
        _block_unplug(vm, dev)
        time.sleep(3)

    error_context.context("Try to log into guest '%s'." % vm.name,
                          logging.info)
    session = vm.wait_for_login(timeout=240)
    error_context.context("log into guest '%s' successfully." % vm.name,
                          logging.info)

    for i in range(0, 5):
        _block_hotplug(vm, 'hpstg%s' % i)
        time.sleep(3)

    disks = session.cmd_output(cmd='lsblk')
    logging.info(disks)
    query_block = vm.monitor.cmd('query-block')
    logging.info(query_block)

    logging.info(disks)

    session.close()
    vm.destroy(gracefully=True)
