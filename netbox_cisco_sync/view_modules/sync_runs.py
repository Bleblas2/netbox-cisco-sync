"""Widoki historii synchronizacji, usuwania i kontrolowanego Revert."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import View

from netbox.object_actions import DeleteObject
from netbox.views import generic
from utilities.views import register_model_view

from .. import filtersets, tables
from ..models import SyncRun


@register_model_view(SyncRun, name="list", path="", detail=False)
class SyncRunListView(generic.ObjectListView):
    """Historia compare/apply z filtrowaniem po urządzeniu, statusie i trybie."""
    queryset = SyncRun.objects.select_related("config", "device")
    table = tables.SyncRunTable
    filterset = filtersets.SyncRunFilterSet
    # SyncRun jest rekordem audytowym tworzonym wyłącznie przez compare/apply.
    # Pusta lista akcji usuwa z nagłówka niepotrzebny przycisk "+ Add".
    actions = ()


@register_model_view(SyncRun)
class SyncRunView(generic.ObjectView):
    queryset = SyncRun.objects.all()
    # SyncRun jest niezmiennym wpisem audytowym. NetBox domyślnie pokazuje tutaj
    # Clone, Edit i Delete, mimo że dla tego modelu nie istnieje widok edycji.
    actions = (DeleteObject,)


@register_model_view(SyncRun, name="delete")
class SyncRunDeleteView(generic.ObjectDeleteView):
    queryset = SyncRun.objects.all()


@register_model_view(SyncRun, name="bulk_delete", detail=False)
class SyncRunBulkDeleteView(generic.BulkDeleteView):
    queryset = SyncRun.objects.all()
    table = tables.SyncRunTable


@register_model_view(SyncRun, name="revert")
class SyncRunRevertView(LoginRequiredMixin, View):
    """Potwierdzony ręcznie revert tylko obiektów z tabeli SyncRunObject."""
    def get(self, request, pk):
        return render(request, "netbox_cisco_sync/syncrun_revert.html", {"object": get_object_or_404(SyncRun, pk=pk)})

    def post(self, request, pk):
        run = get_object_or_404(SyncRun, pk=pk)
        if not request.user.has_perm("netbox_cisco_sync.change_syncrun"):
            messages.error(request, "You do not have permission to revert this run.")
        elif not run.can_revert:
            messages.warning(request, "Nothing to revert.")
        else:
            messages.success(request, f"Reverted {run.revert()} object(s) created by run #{run.pk}.")
        return redirect(run.get_absolute_url())
