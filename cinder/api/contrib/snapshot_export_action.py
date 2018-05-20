#   Copyright 2013, Red Hat, Inc.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.
#
# Copyright (c) 2014, 2017 Wind River Systems, Inc.
#

import webob

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import volume
from oslo_log import log as logging
from oslo_messaging.rpc import client as rpc_client

import six

WRS_SNAP_EXPORT = 'wrs-snapshot:os-export_snapshot'

LOG = logging.getLogger(__name__)

authorize = extensions.soft_extension_authorizer(
    'volume',
    'snapshot_export_attributes')


class SnapshotExportActionsController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(SnapshotExportActionsController, self).__init__(*args, **kwargs)
        self.volume_api = volume.API()
        LOG.debug("SnapshotActionsController initialized")

    @wsgi.response(202)
    @wsgi.action(WRS_SNAP_EXPORT)
    def _volume_export_snapshot(self, req, id, body):
        """Export a snapshot to a file."""

        context = req.environ['cinder.context']

        LOG.debug("body: %s", body)

        current_snapshot = db.snapshot_get(context, id)

        if current_snapshot['status'] not in {'available'}:
            msg = _("Snapshot status %(cur)s not allowed for "
                    "export_snapshot") % {
                        'cur': current_snapshot['status']}
            raise webob.exc.HTTPBadRequest(explanation=msg)

        LOG.info("Exporting snapshot %(id)s", {'id': id})

        try:
            snapshot = self.volume_api.get_snapshot(context, id)
        except exception.SnapshotNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        try:
            response = self.volume_api.export_snapshot(context, snapshot)
        except exception.InvalidSnapshot as error:
            raise webob.exc.HTTPBadRequest(explanation=error.msg)
        except ValueError as error:
            raise webob.exc.HTTPBadRequest(explanation=six.text_type(error))
        except rpc_client.RemoteError as error:
            msg = "%(err_type)s: %(err_msg)s" % {'err_type': error.exc_type,
                                                 'err_msg': error.value}
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return {WRS_SNAP_EXPORT: response}

    def _get_snapshots(self, context):
        snapshots = self.volume_api.get_all_snapshots(context)
        rval = {(snapshot['id'], snapshot) for snapshot in snapshots}
        return rval

    def _export_snapshot(self, req, resp_snap):
        db_snap = req.cached_resource_by_id(resp_snap['id'], name='snapshots')
        for attr in ['backup_status']:
            key = "%s:%s" % (Snapshot_export_action.alias, attr)
            resp_snap[key] = db_snap[attr]

    @wsgi.extends
    def show(self, req, resp_obj, id):
        if req.headers.get('wrs-header') is not None:
            context = req.environ['cinder.context']
            if authorize(context):
                snapshot = resp_obj.obj['snapshot']
                self._export_snapshot(req, snapshot)

    @wsgi.extends
    def detail(self, req, resp_obj):
        if req.headers.get('wrs-header') is not None:
            context = req.environ['cinder.context']
            if authorize(context):
                for snapshot in list(resp_obj.obj['snapshots']):
                    self._export_snapshot(req, snapshot)


class Snapshot_export_action(extensions.ExtensionDescriptor):
    """Enable snapshot export to file"""

    name = "SnapshotExportAction"
    alias = "wrs-snapshot"
    updated = "2014-08-16T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = SnapshotExportActionsController()
        extension = extensions.ControllerExtension(self,
                                                   'snapshots',
                                                   controller)
        return [extension]


def make_snapshot(elem):
    elem.set('{%s}backup_status' % Snapshot_export_action.namespace,
             '%s:backup_status' % Snapshot_export_action.alias)
