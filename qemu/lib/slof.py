import re
import time
import logging


def boot_context(vm):
    context = ''
    with open(vm.serial_console_log) as f:
        for line in f.readlines():
            context = context + line
            if 'Successfully loaded' in line:
                return context
            elif '0 >' in line:
                return context


def wait_for_load(vm, timeout):
    start_time = time.time()
    end_time = float(timeout) + start_time

    while time.time() < end_time:
        try:
            if boot_context(vm):
                return True
        except:
            continue
    return False


def build_date(vm):
    for line in boot_context(vm).splitlines():
        if 'Build Date' in line:
            return line.split('=')[-1].strip()
    return None


def fw_version(vm):
    for line in boot_context(vm).splitlines():
        if 'FW Version' in line:
            return line.split('=')[-1].strip()
    return None


def polulate_vios(vm):
    vios_list = []
    for line in boot_context(vm).splitlines():
        if re.search(r'\s+Populating /vdevice', line):
            vios_list.append(line.split('Populating')[-1].strip())
    return vios_list


def populate_pci_busses(vm):
    pci_bus_list = []
    for line in boot_context(vm).splitlines():
        if re.search(r'\s+Populating /pci', line):
            pci_bus_list.append(line.split('Populating')[-1].strip())
    return pci_bus_list


def boot_device(vm):
    booted_dict = {}
    for line in boot_context(vm).splitlines():
        if re.search(r'\s+Trying to load:\s+from:\s', line):
            device_name = line.split('from:')[-1].strip().replace(' ...', '')
            device_index = boot_context(vm).splitlines().index(line)
            boot_status = boot_context(vm).splitlines()[device_index + 1]
            booted_dict[device_name] = re.split(r'\d{2}:\d{2}:\d{2}:',
                                                boot_status)[-1].strip()
    return booted_dict


def verify_boot_device(vm, parent_bus_type, child_bus_type, child_addr,
                       sub_child_addr=None):
    if '0x' in child_addr:
        addr = child_addr[2:].lstrip('0')
    else:
        addr = child_addr
    if sub_child_addr:
        if '0x' in sub_child_addr:
            sub_addr = sub_child_addr[2:].lstrip('0')
        else:
            sub_addr = sub_child_addr

    pattern = re.compile(r'/\w+.{1}\w+@')
    for dev_name, dev_status in boot_device(vm).items():
        if parent_bus_type == 'pci':
            # virtio-bkl and virtio-scsi device
            if child_bus_type == 'scsi':
                if addr == pattern.split(dev_name)[2]:
                    return True
            # pci-bridge device, usb
            elif child_bus_type == 'pci-bridge' or child_bus_type == 'usb':
                if addr == pattern.split(dev_name)[2] and sub_addr == \
                        pattern.split(dev_name)[3]:
                    return True
        elif parent_bus_type == 'vdevice':
            if child_bus_type == 'v-scsi':
                if addr == pattern.split(dev_name)[1]:
                    return True
    return False


def check_error(vm):
    for line in boot_context(vm).splitlines():
        if re.search(r'(E|e)rror|ERROR', line):
            return line
    return None