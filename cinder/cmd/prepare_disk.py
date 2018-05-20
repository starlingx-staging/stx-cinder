#!/usr/bin/env python 
#
# Copyright (c) 2017 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# flake8: noqa

# prepare_disk purpose is to replace the following packstack/puppet
# fragment in *_drbd_cinder.pp
#
#   # The disk is partitioned here to allow us to use only a portion of the
#   # disk for our VG.
#   exec { 'Create partition table':
#       path    => [ '/usr/bin', '/usr/sbin', '/usr/local/bin', '/etc', '/sbin', '/bin' ],
#       command => 'parted -a optimal --script ${cinder_disk} -- mktable gpt',
#   } ->
#   exec { 'Create primary partition':
#       path    => [ '/usr/bin', '/usr/sbin', '/usr/local/bin', '/etc', '/sbin', '/bin' ],
#       command => 'parted -a optimal --script ${cinder_disk} -- mkpart primary 2 ${cinder_size}GiB',
#   } ->
#   exec { 'Wait for udev before continuing':
#       path    => [ '/usr/bin', '/usr/sbin', '/usr/local/bin', '/etc', '/sbin', '/bin' ],
#       command => 'udevadm settle',
#   } ->
#   exec { 'Wipe':
#       path    => [ '/usr/bin', '/usr/sbin', '/usr/local/bin', '/etc', '/sbin', '/bin' ],
#       command => 'wipefs -a ${cinder_device}',
#   } ->
#
# and to enhance it by re-using cinder device if it's already present and
# matches expected disk, device, and size requirements. It makes the same
# assumptions as packstack/puppet fragment:
#   1. ${cinder-device} is the first partition on ${cinder-disk}
#   2. ${cinder-disk} partitions are not mounted

import argparse
import collections
import logging
import subprocess
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s cinder prepare_disk %(levelname)s [-] %(message)s')
LOG = logging

PARTED_FIELD_SEPARATOR = ':'


class PartInfo(collections.namedtuple(
    'PartInfo', ['number', 'begin_gib', 'end_gib', 'size_gib',
                 'filesystem_type', 'partition_name', 'flags'])):
    def __new__(cls, parted_info):
        info = parted_info.split(PARTED_FIELD_SEPARATOR)
        # noinspection PyArgumentList
        return super(PartInfo, cls).__new__(
            cls, int(info[0]) - 1,
            float(info[1].replace('GiB', '')),
            float(info[2].replace('GiB', '')),
            float(info[3].replace('GiB', '')),
            info[4], info[5], info[6])


class DiskInfo(collections.namedtuple(
    'DiskInfo', ['path', 'size', 'transport_type',
                 'logical_sector_size', 'physical_sector_size',
                 'partition_table_type', 'model_name', 'flags',
                 'partition'])):
    PARTED_UNITS_LINE_NUMBER = 0
    PARTED_UNITS_EXPECTED = 'BYT'
    PARTED_DISK_INFO_LINE_NUMBER = 1
    PARTED_PART_INFO_LINE_START = 2

    def __new__(cls, disk_node):
        info = []
        try:
            for line in subprocess.check_output(
                    ['parted', '--script', '--machine', disk_node,
                     'unit GiB print'],
                    stderr=subprocess.STDOUT).split(';'):
                line = line.strip()
                if len(line):
                    info.append(line)
        except subprocess.CalledProcessError as e:
            raise DiskInfoUnavailable(
                command=' '.join(e.cmd), retcode=e.returncode,
                output=e.output.strip())
        if info[cls.PARTED_UNITS_LINE_NUMBER] != cls.PARTED_UNITS_EXPECTED:
            raise DiskInfoNotSupported(
                expected=info[cls.PARTED_UNITS_LINE_NUMBER],
                actual=cls.PARTED_UNITS_EXPECTED)
        disk_info = info[cls.PARTED_DISK_INFO_LINE_NUMBER].split(
            PARTED_FIELD_SEPARATOR)
        partitions = {}
        for p in info[cls.PARTED_PART_INFO_LINE_START:]:
            part_info = PartInfo(p)
            partitions[part_info[0]] = part_info
        # noinspection PyArgumentList
        return super(DiskInfo, cls).__new__(
            cls, *disk_info, partition=partitions)


class PrepareDiskException(Exception):
    critical = True
    message = ''

    def __init__(self, **kwargs):
        if len(kwargs):
            self.message = self.message.format(**kwargs)


class DiskInfoNotSupported(PrepareDiskException):
    message = ('Disk info units not supported: '
               'expected={expected}, '
               'actual={actual}')


class DiskInfoUnavailable(PrepareDiskException):
    message = ('Partition info unavailable: command="{command}", '
               'return_code={retcode}, output="{output}"')


class PartitionTableTypeMismatch(PrepareDiskException):
    critical = False
    message = ('Partition table type mismatch: disk={disk}, '
               'expected={expected}, actual={actual}')


class PartitionCountMismatch(PrepareDiskException):
    critical = False
    message = ('Partition count mismatch: disk={disk}, '
               'expected={expected}, actual={actual}')


class PartitionSizeMismatch(PrepareDiskException):
    critical = False
    message = ('Partition size mismatch: disk={disk}, '
               'expected_size={expected:.02f}GiB, '
               'actual_size={actual:.02f}GiB')


class CreatePartitionTableFailed(PrepareDiskException):
    message = ('Failed to create partition table: '
               'disk={disk}, command="{command}", '
               'return_code={retcode}, output="{output}"')


class CreatePartitionFailed(PrepareDiskException):
    message = ('Failed to create cinder partition: '
               'disk={disk}, command="{command}", '
               'return_code={retcode}, output="{output}"')


class WipeFilesystemFailed(PrepareDiskException):
    critical = False
    message = ('Failed to wipe file system: '
               'device={device}, command="{command}", '
               'return_code={retcode}, output="{output}"')


def check_cinder_disk(disk, size_gib):
    subprocess.call(['udevadm', 'settle', '--exit-if-exists', disk])
    disk_node = subprocess.check_output([
        'readlink', '-f', disk]).strip()
    disk_info = DiskInfo(disk_node)
    LOG.info('Check disk {} partition table type is gpt'.format(disk))
    if disk_info.partition_table_type.lower() != 'gpt':
        raise PartitionTableTypeMismatch(
            disk=disk_node, expected='gpt',
            actual=disk_info.partition_table_type.lower())
    LOG.info('Check disk {} has exactly one partition'.format(disk))
    if len(disk_info.partition) != 1:
        raise PartitionCountMismatch(
            disk=disk_node, expected=1,
            actual=len(disk_info.partition))
    LOG.info(('Check disk {} partition 1 '
              'size is {:.02f}GiB').format(disk, size_gib))
    if disk_info.partition[0].size_gib != size_gib:
        raise PartitionSizeMismatch(
            disk=disk_node, expected=size_gib,
            actual=disk_info.partition[0].size_gib)


def create_cinder_device(disk, device, size_gib):
    try:
        LOG.info(('Create gpt partition table '
                  'on disk {}').format(disk))
        subprocess.check_output([
            'parted', '--align', 'optimal', '--script', disk,
            'mktable gpt'],
            stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise CreatePartitionTableFailed(
            disk=disk, command=' '.join(e.cmd),
            retcode=e.returncode, output=e.output.strip())
    try:
        LOG.info(('Create cinder partition '
                  'on disk {} of size {}GiB').format(disk, size_gib))
        subprocess.check_output([
            'parted', '--align', 'optimal', '--script', disk,
            'mkpart primary 2 {}GiB'.format(size_gib)])
    except subprocess.CalledProcessError as e:
        raise CreatePartitionFailed(
            disk=disk, command=' '.join(e.cmd),
            retcode=e.returncode, output=e.output.strip())
    subprocess.call(['udevadm', 'settle', '--exit-if-exists', device])
    try:
        LOG.info('Wipe device {} file system'.format(device))
        subprocess.check_output([
            'wipefs', '--all', device],
            stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise WipeFilesystemFailed(
            device=device, command=' '.join(e.cmd),
            retcode=e.returncode, output=e.output.strip())


def prepare_cinder_device(path, device, size_gib):
    try:
        check_cinder_disk(path, size_gib)
        LOG.info('Cinder disk OK: path={}, size={}GiB'.format(path, size_gib))
        return
    except PrepareDiskException as e:
        if e.critical:
            raise
        LOG.warning(e.message)
    LOG.warning('Recovery action: create and wipe cinder device')
    try:
        create_cinder_device(path, device, size_gib)
    except PrepareDiskException as e:
        if e.critical:
            raise
        LOG.warning(e.message)


def main():
    parser = argparse.ArgumentParser(description='Prepare Cinder disk')
    parser.add_argument(
        'disk_path',
        help='/dev/disk/by-path/* disk to be used by Cinder')
    parser.add_argument(
        'device_path',
        help='/dev/disk/by-path/*-part* device to be used by Cinder')
    parser.add_argument(
        'size_gib', type=float, help='Cinder device size (GiB)')
    args = parser.parse_args()
    try:
        prepare_cinder_device(args.disk_path, args.device_path, args.size_gib)
    except Exception as e:
        LOG.exception('Error: {}'.format(e.message))
        sys.exit(1)
