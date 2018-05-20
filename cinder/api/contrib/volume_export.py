#   Copyright (c) 2014 Wind River Systems, Inc.
#   Copyright 2012 OpenStack Foundation
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
# Copyright (c) 2017 Wind River Systems, Inc.
#


import webob

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder import exception
from cinder.i18n import _
from cinder import volume
from oslo_log import log as logging
from oslo_messaging.rpc import client as rpc_client

import six

WRS_VOL_EXPORT = 'wrs-volume:os-volume_export'
WRS_VOL_IMPORT = 'wrs-volume:os-volume_import'

LOG = logging.getLogger(__name__)

authorize = extensions.soft_extension_authorizer(
    'volume',
    'volume_backup_status_attribute')


class VolumeExportController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(VolumeExportController, self).__init__(*args, **kwargs)
        self.volume_api = volume.API()

    @wsgi.response(202)
    @wsgi.action(WRS_VOL_EXPORT)
    def _volume_export(self, req, id, body):
        """Exports the specified volume to a file."""
        context = req.environ['cinder.context']
        if WRS_VOL_EXPORT not in body:
            msg = _("Invalid request body")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        try:
            response = self.volume_api.export_volume(context,
                                                     volume)
        except exception.InvalidVolume as error:
            raise webob.exc.HTTPBadRequest(explanation=error.msg)
        except ValueError as error:
            raise webob.exc.HTTPBadRequest(explanation=six.text_type(error))
        except rpc_client.RemoteError as error:
            msg = "%(err_type)s: %(err_msg)s" % {'err_type': error.exc_type,
                                                 'err_msg': error.value}
            raise webob.exc.HTTPBadRequest(explanation=msg)
        return {WRS_VOL_EXPORT: response}

    @wsgi.response(202)
    @wsgi.action(WRS_VOL_IMPORT)
    def _volume_import(self, req, id, body):
        """Imports the specified volume from a file."""
        context = req.environ['cinder.context']
        try:
            params = body[WRS_VOL_IMPORT]
        except (TypeError, KeyError):
            msg = _("Invalid request body")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        if not params.get("file_name"):
            msg = _("No file_name was specified in request.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            volume = self.volume_api.get(context, id)
        except exception.VolumeNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        try:
            response = self.volume_api.import_volume(context,
                                                     volume,
                                                     params["file_name"])
        except exception.InvalidVolume as error:
            raise webob.exc.HTTPBadRequest(explanation=error.msg)
        except ValueError as error:
            raise webob.exc.HTTPBadRequest(explanation=six.text_type(error))
        except rpc_client.RemoteError as error:
            msg = "%(err_type)s: %(err_msg)s" % {'err_type': error.exc_type,
                                                 'err_msg': error.value}
            raise webob.exc.HTTPBadRequest(explanation=msg)
        return {WRS_VOL_IMPORT: response}

    def _add_volume_backup_status_attribute(self, context, resp_volume):
        try:
            db_volume = self.volume_api.get(context, resp_volume['id'])
        except Exception:
            return
        else:
            key = "%s:backup_status" % Volume_export.alias
            resp_volume[key] = db_volume['backup_status']

    @wsgi.extends
    def show(self, req, resp_obj, id):
        if req.headers.get('wrs-header') is not None:
            context = req.environ['cinder.context']
            if authorize(context):
                self._add_volume_backup_status_attribute(context,
                                                         resp_obj
                                                         .obj['volume'])

    @wsgi.extends
    def detail(self, req, resp_obj):
        if req.headers.get('wrs-header') is not None:
            context = req.environ['cinder.context']
            if authorize(context):
                for vol in list(resp_obj.obj['volumes']):
                    self._add_volume_backup_status_attribute(context, vol)


class Volume_export(extensions.ExtensionDescriptor):
    """Enable volume export/import"""

    name = "VolumeExport"
    alias = "wrs-volume"
    updated = "2014-08-11T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeExportController()
        extension = extensions.ControllerExtension(self, 'volumes', controller)
        return [extension]


def make_volume(elem):
    elem.set('{%s}backup_status' % Volume_export.namespace,
             '%s:backup_status' % Volume_export.alias)
