"""
slof_boot.py include following case:
1.  Boot guest from virtio HDD and check guest can be boot successfully
2.  Boot guest from virtio HDD with dataplane and check guest can be boot successfully
3.  Boot guest from virtio scsi HDD and check guest can be boot successfully
4.  Boot guest from virtio scsi HDD with dataplane and check guest can be boot successfully
5.  Boot guest from spapr-vscsi HDD and check guest can be boot successfully
6.  Boot guest from usb storage and check guest can be boot successfully
7.  SLOF can boot from virtio-scsi disk behind pci-bridge
8.  SLOF can boot from virtio-blk-pci disk behind pci-bridge
9.  Test supported block size of boot disk for virtio-blk-pci
10. Test supported block size of boot disk for virtio-scsi

:author: Yongxue Hong <yhong@redhat.com>
"""
import logging

from virttest import error_context
from qemu.lib import slof
from virttest import utils_net


@error_context.context_aware
def run(test, params, env):
    timeout = float(params.get("login_timeout", 240))
    vm = env.get_vm(params['main_vm'])

    if not slof.wait_for_load(vm, timeout):
        test.fail('SLOF boot failed under %s sec.' % timeout)

    logging.debug('Output of SLOF:\n%s' % slof.boot_context(vm))

    error_context.context("Check the output of SLOF.", logging.info)
    ret = slof.check_error(vm)
    if ret:
        test.fail("Found error info: %s ." % ret)
    error_context.context("No any error info", logging.info)

    if params.get('boot_device_type') == 'virtio_blk' or \
            params.get('boot_device_type') == 'virtio_scsi':
        child_addr = params.get('addr_pci_bridge1', None)
        if params.get('boot_device_type') == 'virtio_scsi':
            sub_child_addr = params['virtio_scsi_pci_addr']
        else:
            sub_child_addr = str(hex(int(params['drive_pci_addr_image1'])))
        if not child_addr:
            error_context.context(
                "Verify whether booting from specified device(scsi_addr=%s)."
                % sub_child_addr, logging.info)
            if not slof.verify_boot_device(vm, 'pci', 'scsi', sub_child_addr):
                test.fail("Failed to boot from scsi@%s" % sub_child_addr)
            else:
                error_context.context("Boot from scsi@%s successfully."
                                      % sub_child_addr, logging.info)
        else:
            error_context.context(
                "Verify whether booting from specified device(pci_addr=%s,scsi_addr=%s)."
                % (child_addr, sub_child_addr), logging.info)
            if not slof.verify_boot_device(vm, 'pci', 'pci-bridge',
                                           child_addr, sub_child_addr):
                test.fail("Failed to boot from pci@%s/scsi@%s"
                          % (child_addr, sub_child_addr))
            else:
                error_context.context("Boot from pci@%s/scsi@%s successfully."
                                      % (child_addr, sub_child_addr), logging.info)
    elif params.get('boot_device_type') == 'spapr_vscsi':
        child_addr = params['spapr_vscsi_reg']
        error_context.context(
            "Verify whether booting from specified device(addr=%s)."
            % child_addr, logging.info)
        if not slof.verify_boot_device(vm, 'vdevice', 'v-scsi', child_addr):
            test.fail("Failed to boot from v-scsi@%s" % child_addr)
        else:
            error_context.context("Boot from v-scsi@%s successfully."
                                  % child_addr, logging.info)
    elif params.get('boot_device_type') == 'usb_storage':
        child_addr = params['pci_addr_usb1']
        usb_port = params['drive_scsiid_image1']
        error_context.context(
            "Verify whether booting from specified device(addr=%s, port=%s)."
            % (child_addr, usb_port), logging.info)
        if not slof.verify_boot_device(vm, 'pci', 'usb', child_addr, usb_port):
            test.fail("Failed to boot from usb@%s/storage@%s"
                      % (child_addr, usb_port))
        else:
            error_context.context("Boot from usb@%s/storage@%s successfully."
                                  % (child_addr, usb_port), logging.info)

    error_context.context("Try to log into guest '%s'." % vm.name,
                          logging.info)
    session = vm.wait_for_login(timeout=timeout)
    error_context.context("log into guest '%s' successfully." % vm.name,
                          logging.info)

    error_context.context("Try to ping external host.", logging.info)
    extra_host_ip = utils_net.get_host_ip_address(params)
    s, o = session.cmd_status_output('ping %s -c 5' % extra_host_ip)
    logging.debug(o)
    if s:
        test.fail("Failed to ping external host.")
    else:
        error_context.context("Ping host(%s) successfully." % extra_host_ip,
                              logging.info)

    session.close()
    vm.destroy(gracefully=True)
