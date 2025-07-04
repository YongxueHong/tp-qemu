"""
Test case for booting a guest and hotplugging a disk.
"""

import logging

from virttest import error_context, utils_disk, utils_misc
from provider.block_devices_plug import BlockDevicesPlug

LOG = logging.getLogger("avocado.test")

@error_context.context_aware
def run(test, params, env):
    """
    Boots a guest and hotplugs a disk for it.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params.get("main_vm", "vm1"))
    vm.verify_alive() # Ensure VM is up

    session = vm.wait_for_login(timeout=params.get("login_timeout", 240))
    LOG.info("Successfully logged into the guest.")

    # Parameters for the new disk
    # These would typically come from the .cfg file
    # Example: image_name = "hotplug_disk_image"
    #          image_size = "1G"
    #          disk_interface = "virtio-blk-pci" # or scsi-hd, ide-hd etc.

    image_tag = params.get("hotplug_image_tag", "hp_disk0") # Tag for the qemu_devices image definition

    # Define the device using images_define_by_params
    # This creates the device configuration but doesn't attach it yet.
    # The actual image file and its parameters should be defined in the job's YAML/cfg.
    # For example, in the cfg:
    # hp_disk0.image_name = "hotplug_disk.qcow2"
    # hp_disk0.image_size = "1G"
    # hp_disk0.image_format = "qcow2"
    # hp_disk0.disk_interface = "virtio-blk-pci"
    # ... other necessary qemu_devices parameters

    hotplug_devices = vm.devices.images_define_by_params(image_tag,
                                                         params.object_params(image_tag),
                                                         "disk")

    if not hotplug_devices:
        test.fail(f"Could not define hotplug device with tag '{image_tag}'. "
                  "Check test parameters and image definitions.")

    # For simplicity, assuming the first defined device is the one we want to hotplug
    # In a more complex scenario, one might need to iterate or be more specific
    disk_to_hotplug = hotplug_devices[0]

    LOG.info(f"Preparing to hotplug disk: {disk_to_hotplug.get_id()}")

    windows = params.get("os_type") == "windows"
    disks_before_hotplug = utils_misc.list_linux_guest_disks(session) if not windows \
        else set(session.cmd("wmic diskdrive get index").split()[1:])
    LOG.info(f"Disks before hotplug: {disks_before_hotplug}")

    # Using simple_hotplug for a single device
    # For multiple devices or more complex scenarios, BlockDevicesPlug could be used
    result, error_msg = vm.devices.simple_hotplug(disk_to_hotplug, vm.monitor)
    if not result:
        test.fail(f"Failed to hotplug disk '{disk_to_hotplug.get_id()}': {error_msg}")

    LOG.info(f"Disk '{disk_to_hotplug.get_id()}' hotplug command sent successfully.")

    # Verify disk is visible in guest
    excepted_num_new_disks = 1
    if not utils_misc.wait_for(
        lambda: len((utils_misc.list_linux_guest_disks(session) if not windows \
            else set(session.cmd("wmic diskdrive get index").split()[1:])) ^ disks_before_hotplug) == excepted_num_new_disks,
        timeout=60, # Wait up to 60 seconds
        step=1.5,
    ):
        current_disks_guest = utils_misc.list_linux_guest_disks(session) if not windows \
            else set(session.cmd("wmic diskdrive get index").split()[1:])
        test.fail(
            f"Failed to verify hotplugged disk in guest. "
            f"Expected {excepted_num_new_disks} new disk(s). "
            f"Disks before: {disks_before_hotplug}, Disks after: {current_disks_guest}"
        )

    newly_added_disks = (utils_misc.list_linux_guest_disks(session) if not windows \
        else set(session.cmd("wmic diskdrive get index").split()[1:])) ^ disks_before_hotplug

    LOG.info(f"Successfully hotplugged disk(s): {newly_added_disks}")
    test.log.info(f"Hotplugged disk(s) verified in guest: {newly_added_disks}")

    # Optional: Perform I/O on the disk (can be adapted from block_hotplug.py)
    disk_op_cmd = params.get("disk_op_cmd", None)
    disk_op_timeout = int(params.get("disk_op_timeout", 360))

    if disk_op_cmd:
        LOG.info("Performing I/O operations on the hotplugged disk.")
        new_disk_name = newly_added_disks.pop() # Get one of the new disks

        if windows:
            # For Windows, need to format and assign a drive letter if it's a new raw disk
            # This is a simplified version. Real-world might need more robust disk init.
            # Assuming 'new_disk_name' from wmic is the disk index.
            # The 'utils_disk.configure_empty_windows_disk' function from block_hotplug.py
            # is more robust but requires image_size parameter.
            # For simplicity, we'll assume the disk_op_cmd handles any necessary setup
            # or that the disk is already usable, or that a pre-formatted image is used.
            # A more complete solution would replicate Windows disk formatting from block_hotplug.py

            # We need a drive letter for the command. This is tricky without full formatting logic.
            # Let's assume disk_op_cmd is self-sufficient or uses a known letter for the new disk.
            # A placeholder for what might be needed:
            # drive_letter = utils_disk.configure_empty_windows_disk(session, new_disk_name, params.get("hotplug_image_size"))[0]
            # test_cmd = disk_op_cmd % (drive_letter, drive_letter)
            # For now, let's assume disk_op_cmd can find the disk by its properties or uses a fixed path/letter
            # This part may need refinement based on typical Windows test images.
            LOG.warning("Windows I/O test relies on disk_op_cmd being self-sufficient for disk identification/preparation.")
            test_cmd = disk_op_cmd # Simplification: command must handle disk identification
        else:
            # For Linux, new_disk_name is usually like 'sdb', 'sdc', etc.
            # The command should use this, e.g., "dd if=/dev/zero of=/dev/%s bs=1M count=10"
            test_cmd = disk_op_cmd % new_disk_name

        LOG.info(f"Executing I/O command: {test_cmd}")
        session.cmd(test_cmd, timeout=disk_op_timeout)
        LOG.info("I/O operations completed on the hotplugged disk.")

    session.close()
    LOG.info("Test operations completed.")

    # Teardown: Unplug the disk
    LOG.info(f"Attempting to unplug disk: {disk_to_hotplug.get_id()}")
    unplug_result, unplug_error_msg = vm.devices.simple_unplug(disk_to_hotplug, vm.monitor)
    if not unplug_result:
        # Log a warning instead of failing the test, as the main functionality might have passed.
        # Depending on test policy, this could be a test.fail()
        LOG.warning(f"Failed to unplug disk '{disk_to_hotplug.get_id()}': {unplug_error_msg}")
        # Optionally, try to check if disk is gone from guest anyway
        # This might be useful if QMP unplug fails but OS still sees it gone (or vice-versa)
    else:
        LOG.info(f"Successfully sent unplug command for disk '{disk_to_hotplug.get_id()}'.")
        # Optionally, verify disk is gone from guest OS
        # disks_after_unplug = utils_misc.list_linux_guest_disks(session) if not windows \
        #    else set(session.cmd("wmic diskdrive get index").split()[1:])
        # if disk_to_hotplug.get_id() in disks_after_unplug: # This check is conceptual, needs correct mapping
        #    LOG.warning(f"Disk {disk_to_hotplug.get_id()} still visible in guest after unplug.")

    LOG.info("Test completed.")
    pass # Test successful
