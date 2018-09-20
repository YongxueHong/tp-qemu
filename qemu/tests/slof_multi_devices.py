"""
slof_multi_devices.py include following case:
1. SLOF boot successfully when adding two pci-bridge to the guest
2. VM boot successfully with lots of virtio-net-pci devices

:author: Yongxue Hong <yhong@redhat.com>
"""

import logging

from virttest import error_context
from qemu.lib import slof
from virttest import utils_net
from virttest import env_process
from virttest import utils_disk


@error_context.context_aware
def run(test, params, env):
    vm = env.get_vm(params["main_vm"])

    if params['device_type'] == 'pci-bridge':
        for id in range(1, 3):
            params['pci_controllers'] += ' pci_bridge%d' % id
            params['type_pci_bridge%d' % id] = 'pci-bridge'
    elif params['device_type'] == 'virtio-net-pci':
        for id in range(1, 27):
            params['pci_controllers'] += ' pci_bridge%d' % id
            params['type_pci_bridge%d' % id] = 'pci-bridge'

    vm.create(params=params)
    env_process.process(test, params, env, env_process.preprocess_image,
                        env_process.preprocess_vm)

    timeout = float(params.get("login_timeout", 240))
    if not slof.wait_for_load(vm, timeout):
        test.fail('SLOF boot failed under %s sec.' % timeout)

    logging.debug('Output of SLOF:\n%s' % slof.boot_context(vm))

    error_context.context("Check the output of SLOF.", logging.info)
    ret = slof.check_error(vm)
    if ret:
        test.fail("Found error info: %s ." % ret)
    error_context.context("No any error info", logging.info)

    error_context.context("Try to log into guest '%s'." % vm.name,
                          logging.info)
    session = vm.wait_for_login(timeout=timeout)
    error_context.context("log into guest '%s' successfully." % vm.name,
                          logging.info)

    # ====================================================================================================
    # ====================================================================================================

    o = utils_disk.get_linux_disks(session, partition=False)
    logging.debug(o)
    o = utils_disk.get_linux_disks(session, partition=True)
    logging.debug(o)
    # utils_disk.delete_partition_linux(session, 'sdb1', timeout=360)

    utils_disk.create_partition_table_linux(session, 'sdb', 'gpt')
    logging.debug('sdb size:1G start:1M')
    utils_disk.create_partition_linux(session, 'sdb', '10.12GB', '1MB', timeout=360)
    logging.debug(session.cmd_output('parted /dev/sdb unit MiB print'))
    logging.debug(session.cmd_output('parted /dev/sdb unit MB print'))
    utils_disk.delete_partition_linux(session, 'sdb1', timeout=360)

    logging.debug('sdc size:0M start:1M')
    utils_disk.create_partition_table_linux(session, 'sdc', 'gpt')
    utils_disk.create_partition_linux(session, 'sdc', '0M', '1MB', timeout=360)
    logging.debug(session.cmd_output('parted /dev/sdb unit MiB print'))
    logging.debug(session.cmd_output('parted /dev/sdb unit MB print'))
    utils_disk.delete_partition_linux(session, 'sdc1', timeout=360)

    logging.debug('sdd size:1GiB start:1MiB')
    utils_disk.create_partition_table_linux(session, 'sdd', 'gpt')
    utils_disk.create_partition_linux(session, 'sdd', '10.123GiB', '1MiB', timeout=360)
    logging.debug(session.cmd_output('parted /dev/sdb unit MiB print'))
    logging.debug(session.cmd_output('parted /dev/sdb unit MB print'))
    utils_disk.delete_partition_linux(session, 'sdd1', timeout=360)

    # logging.debug('sdb size:1KB start:1KB')
    # utils_disk.create_partition_linux(session, 'sdb', '1K', '1K', timeout=360)
    # logging.debug(session.cmd_output('parted /dev/sdb unit MiB print'))
    # logging.debug(session.cmd_output('parted /dev/sdb unit MB print'))
    # utils_disk.delete_partition_linux(session, 'sdb1', timeout=360)

    logging.debug('sdb size:19GiB start:1MiB')
    utils_disk.create_partition_table_linux(session, 'sdb', 'gpt')
    utils_disk.create_partition_linux(session, 'sdb', '19GiB', '1MiB', timeout=360)
    logging.debug(session.cmd_output('parted /dev/sdb unit MiB print'))
    logging.debug(session.cmd_output('parted /dev/sdb unit MB print'))
    utils_disk.delete_partition_linux(session, 'sdb1', timeout=360)

    logging.debug('========configure_empty_linux_disk sdb========')
    utils_disk.configure_empty_linux_disk(session, 'sdb', '20GiB', start="1MiB", n_partitions=10,
                               fstype="ext4",
                               labeltype='gpt',
                               timeout=360)
    logging.debug(session.cmd_output('parted /dev/sdb unit MiB print'))
    logging.debug(session.cmd_output('parted /dev/sdb unit MB print'))

    logging.debug('========clean_partition_linux sdb========')
    utils_disk.clean_partition_linux(session, 'sdb', timeout=360)
    logging.debug(session.cmd_output('parted /dev/sdb unit MiB print'))
    logging.debug(session.cmd_output('parted /dev/sdb unit MB print'))

    logging.debug('========configure_empty_linux_disk sdd========')
    utils_disk.configure_empty_linux_disk(session, 'sdd', '30GiB', "1MiB", n_partitions=30,
                               fstype="xfs",
                               labeltype='gpt',
                               timeout=360)
    logging.debug(session.cmd_output('parted /dev/sdd unit MiB print'))
    logging.debug(session.cmd_output('parted /dev/sdd unit MB print'))

    utils_disk.delete_partition_linux(session, 'sdb25', timeout=360)
    logging.debug(session.cmd_output('parted /dev/sdd unit MiB print'))
    logging.debug(session.cmd_output('parted /dev/sdd unit MB print'))
    # ====================================================================================================
    # ====================================================================================================

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
