"""
fullscreen_setup.py - Used as a setup test for the full-screen test.

To make sure the full screen test is tested correctly, this setup will
change the resolution of the guest, by default creating two VMs from
the same setup will result in them having the same resolution.

"""

from virttest import utils_spice


def run(test, params, env):
    """
    Simple test for Remote Desktop connection
    Tests expectes that Remote Desktop client (spice/vnc) will be executed
    from within a second guest so we won't be limited to Linux only clients

    The plan is to support remote-viewer at first place

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    # Get necessary params
    test_timeout = float(params.get("test_timeout", 600))

    utils_spice.wait_timeout(20)

    for vm in params.get("vms").split():
        utils_spice.clear_interface(
            env.get_vm(vm), int(params.get("login_timeout", "360"))
        )

    utils_spice.wait_timeout(20)

    guest_vm = env.get_vm(params["guest_vm"])
    guest_vm.verify_alive()
    guest_session = guest_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360))
    )
    guest_root_session = guest_vm.wait_for_login(username="root", password="123456")
    client_vm = env.get_vm(params["client_vm"])
    client_vm.verify_alive()
    client_session = client_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360))
    )
    client_vm.wait_for_login(username="root", password="123456")

    test.log.debug("Exporting client display")
    client_session.cmd("export DISPLAY=:0.0")

    # Get the min, current, and max resolution on the guest
    output = client_session.cmd("xrandr | grep Screen")
    outputlist = output.split()

    minimum = "640x480"

    current_index = outputlist.index("current")
    current = outputlist[current_index + 1]
    current += outputlist[current_index + 2]
    # Remove trailing comma
    current += outputlist[current_index + 3].replace(",", "")

    maximum = "2560x1600"

    test.log.info("Minimum: %s Current: %s Maximum: %s", minimum, current, maximum)
    if current != minimum:
        newClientResolution = minimum
    else:
        newClientResolution = maximum

    # Changing the guest resolution
    client_session.cmd("xrandr -s " + newClientResolution)
    test.log.info(
        "The resolution on the client has been changed from %s to: %s",
        current,
        newClientResolution,
    )

    test.log.debug("Exporting guest display")
    guest_session.cmd("export DISPLAY=:0.0")

    # Get the min, current, and max resolution on the guest
    output = guest_session.cmd("xrandr | grep Screen")
    outputlist = output.split()

    current_index = outputlist.index("current")
    currentGuestRes = outputlist[current_index + 1]
    currentGuestRes += outputlist[current_index + 2]
    currentGuestRes += outputlist[current_index + 3].replace(",", "")
    test.log.info("Current Resolution of Guest: %s", currentGuestRes)

    if newClientResolution == currentGuestRes:
        test.fail("Client resolution is same as guest resolution!")

    # Start vdagent daemon
    utils_spice.start_vdagent(guest_root_session, test_timeout)

    client_session.close()
    guest_session.close()
