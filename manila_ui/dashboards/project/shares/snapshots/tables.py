# Copyright 2012 Nebula, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from django.core.urlresolvers import NoReverseMatch  # noqa
from django.core.urlresolvers import reverse
from django.template.defaultfilters import title  # noqa
from django.utils.http import urlencode  # noqa
from django.utils.translation import pgettext_lazy
from django.utils.translation import string_concat  # noqa
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from horizon import exceptions
from horizon import tables

from manila_ui.api import manila
from openstack_dashboard.usage import quotas


DELETABLE_STATES = ("available", "error")


class UpdateRow(tables.Row):
    ajax = True

    def get_data(self, request, snapshot_id):
        snapshot = manila.share_snapshot_get(request, snapshot_id)
        if not snapshot.name:
            snapshot.name = snapshot_id
        return snapshot


def get_size(snapshot):
    return _("%sGiB") % snapshot.size


class CreateSnapshot(tables.LinkAction):
    name = "snapshots"
    verbose_name = _("Create Snapshot")
    url = "horizon:project:shares:create_snapshot"
    classes = ("ajax-modal", "btn-camera")
    policy_rules = (("share", "share:create_snapshot"),)

    def get_policy_target(self, request, datum=None):
        project_id = None
        if datum:
            project_id = getattr(datum, "project_id", None)
        return {"project_id": project_id}

    def allowed(self, request, share=None):
        usages = quotas.tenant_quota_usages(request)
        if usages['snapshots']['available'] <= 0:
            if "disabled" not in self.classes:
                self.classes = [c for c in self.classes] + ['disabled']
                self.verbose_name = string_concat(self.verbose_name, ' ',
                                                  _("(Quota exceeded)"))
        else:
            self.verbose_name = _("Create Snapshot")
            classes = [c for c in self.classes if c != "disabled"]
            self.classes = classes

        # NOTE(vponomaryov): Disable form with creation of a snapshot for
        # shares that has attr 'snapshot_support' equal to False.
        if hasattr(share, 'snapshot_support'):
            snapshot_support = share.snapshot_support
        else:
            # NOTE(vponomaryov): Allow creation of a snapshot for shares that
            # do not have such attr for backward compatibility.
            snapshot_support = True
        return share.status in ("available", "in-use") and snapshot_support


class DeleteSnapshot(tables.DeleteAction):
    policy_rules = (("share", "share:delete_snapshot"),)

    @staticmethod
    def action_present(count):
        return ungettext_lazy(
            u"Delete Snapshot",
            u"Delete Snapshots",
            count
        )

    @staticmethod
    def action_past(count):
        return ungettext_lazy(
            u"Deleted Snapshot",
            u"Deleted Snapshots",
            count
        )

    def get_policy_target(self, request, datum=None):
        project_id = None
        if datum:
            project_id = getattr(datum, "project_id", None)
        return {"project_id": project_id}

    def delete(self, request, obj_id):
        obj = self.table.get_object_by_id(obj_id)
        name = self.table.get_object_display(obj)
        try:
            manila.share_snapshot_delete(request, obj_id)
        except Exception:
            msg = _('Unable to delete snapshot "%s". One or more shares '
                    'depend on it.')
            exceptions.check_message(["snapshots", "dependent"], msg % name)
            raise

    def allowed(self, request, snapshot=None):
        if snapshot:
            return snapshot.status in DELETABLE_STATES
        return True


class CreateShareFromSnapshot(tables.LinkAction):
    name = "create_from_snapshot"
    verbose_name = _("Create Share")
    url = "horizon:project:shares:create"
    classes = ("ajax-modal", "btn-camera")
    policy_rules = (("share", "share:create"),)

    def get_link_url(self, datum):
        base_url = reverse(self.url)
        params = urlencode({"snapshot_id": self.table.get_object_id(datum)})
        return "?".join([base_url, params])

    def allowed(self, request, share=None):
        return share.status == "available"


class EditSnapshot(tables.LinkAction):
    name = "edit_snapshot"
    verbose_name = _("Edit Snapshot")
    url = "horizon:project:shares:edit_snapshot"
    classes = ("ajax-modal", "btn-camera")


class SnapshotShareNameColumn(tables.Column):
    def get_link_url(self, snapshot):
        return reverse(self.link, args=(snapshot.share_id,))


class ManageRules(tables.LinkAction):
    name = "snapshot_manage_rules"
    verbose_name = _("Manage Rules")
    url = "horizon:project:shares:snapshot_manage_rules"
    classes = ("btn-edit",)
    policy_rules = (("share", "share:access_get_all"),)

    def allowed(self, request, snapshot=None):
        share = manila.share_get(request, snapshot.share_id)
        return share.mount_snapshot_support


class AddRule(tables.LinkAction):
    name = "snapshot_rule_add"
    verbose_name = _("Add rule")
    url = 'horizon:project:shares:snapshot_rule_add'
    classes = ("ajax-modal", "btn-create")
    icon = "plus"
    policy_rules = (("share", "share:allow_access"),)

    def allowed(self, request, snapshot=None):
        snapshot = manila.share_snapshot_get(
            request, self.table.kwargs['snapshot_id'])
        return snapshot.status in ("available", "in-use")

    def get_link_url(self):
        return reverse(self.url, args=[self.table.kwargs['snapshot_id']])


class DeleteRule(tables.DeleteAction):
    policy_rules = (("share", "share:deny_access"),)

    @staticmethod
    def action_present(count):
        return ungettext_lazy(
            u"Delete Rule",
            u"Delete Rules",
            count
        )

    @staticmethod
    def action_past(count):
        return ungettext_lazy(
            u"Deleted Rule",
            u"Deleted Rules",
            count
        )

    def delete(self, request, obj_id):
        try:
            manila.share_snapshot_deny(
                request, self.table.kwargs['snapshot_id'], obj_id)
        except Exception:
            msg = _('Unable to delete snapshot rule "%s".') % obj_id
            exceptions.handle(request, msg)


class UpdateRuleRow(tables.Row):
    ajax = True

    def get_data(self, request, rule_id):
        rules = manila.share_snapshot_rules_list(
            request, self.table.kwargs['snapshot_id'])
        if rules:
            for rule in rules:
                if rule.id == rule_id:
                    return rule
        raise exceptions.NotFound


class RulesTable(tables.DataTable):
    access_type = tables.Column("access_type", verbose_name=_("Access Type"))
    access_to = tables.Column("access_to", verbose_name=_("Access to"))
    status = tables.Column("state", verbose_name=_("Status"))

    def get_object_display(self, obj):
        return obj.id

    class Meta(object):
        name = "rules"
        verbose_name = _("Rules")
        status_columns = ["status"]
        row_class = UpdateRuleRow
        table_actions = (
            AddRule,
            DeleteRule)
        row_actions = (
            DeleteRule,)


class SnapshotsTable(tables.DataTable):
    STATUS_CHOICES = (
        ("in-use", True),
        ("available", True),
        ("creating", None),
        ("error", False),
    )
    STATUS_DISPLAY_CHOICES = (
        ("in-use", pgettext_lazy("Current status of snapshot", u"In-use")),
        ("available", pgettext_lazy("Current status of snapshot",
                                    u"Available")),
        ("creating", pgettext_lazy("Current status of snapshot", u"Creating")),
        ("error", pgettext_lazy("Current status of snapshot", u"Error")),
    )
    name = tables.Column("name",
                         verbose_name=_("Name"),
                         link="horizon:project:shares:snapshot-detail")
    description = tables.Column("description",
                                verbose_name=_("Description"),
                                truncate=40)
    size = tables.Column(get_size,
                         verbose_name=_("Size"),
                         attrs={'data-type': 'size'})
    status = tables.Column("status",
                           filters=(title,),
                           verbose_name=_("Status"),
                           status=True,
                           status_choices=STATUS_CHOICES,
                           display_choices=STATUS_DISPLAY_CHOICES)
    source = SnapshotShareNameColumn("share",
                                     verbose_name=_("Source"),
                                     link="horizon:project:shares:detail")

    def get_object_display(self, obj):
        return obj.name

    class Meta(object):
        name = "snapshots"
        verbose_name = _("Snapshots")
        status_columns = ["status"]
        row_class = UpdateRow
        table_actions = (
            tables.NameFilterAction,
            DeleteSnapshot)
        row_actions = (
            EditSnapshot,
            CreateShareFromSnapshot,
            ManageRules,
            DeleteSnapshot)
