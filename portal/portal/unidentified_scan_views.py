"""
Unidentified scans: visitor photos that matched no collectible (saved by /api/identify).

Researchers (and System Admins) look through them, note what each one shows, and dismiss
or delete the ones that are not useful. Photos older than the retention period are removed
by `manage.py purge_unidentified_scans`.
"""
from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .audit import log_action
from .decorators import feature_required
from .models import AuditLog, UnidentifiedScan
from .roles import get_role
from .views import _safe_date

RECORD_TYPE = "Unidentified Scan"     # label written to the audit log
gate = feature_required("unidentified-scans")


class ReviewForm(forms.ModelForm):
    class Meta:
        model = UnidentifiedScan
        fields = ["status", "kind", "identified_as", "notes"]
        labels = {"kind": "What it shows", "identified_as": "Identified as"}
        widgets = {"notes": forms.Textarea(attrs={"rows": 3}),
                   "identified_as": forms.TextInput(attrs={"placeholder": "e.g. Chrysanthemum"})}

    def clean(self):
        data = super().clean()
        if data.get("status") == UnidentifiedScan.LABELLED and not data.get("kind"):
            self.add_error("kind", "Choose what the photo shows before marking it Labelled.")
        return data


@gate
def scan_list(request):
    scans = UnidentifiedScan.objects.defer("notes")

    status = request.GET.get("status", "")
    outcome = request.GET.get("outcome", "")
    kind = request.GET.get("kind", "")
    q = request.GET.get("q", "").strip()
    date_from = _safe_date(request.GET.get("from"))
    date_to = _safe_date(request.GET.get("to"))

    if status:
        scans = scans.filter(status=status)
    if outcome:
        scans = scans.filter(outcome=outcome)
    if kind:
        scans = scans.filter(kind=kind)
    if q:
        scans = scans.filter(Q(identified_as__icontains=q) | Q(suggested_name__icontains=q)
                             | Q(visitor_username__icontains=q))
    if date_from:
        scans = scans.filter(scanned_at__date__gte=date_from)
    if date_to:
        scans = scans.filter(scanned_at__date__lte=date_to)

    page = Paginator(scans, 15).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)

    return render(request, "portal/unidentified_scan_list.html", {
        "role": get_role(request.user),
        "page": page,
        "statuses": UnidentifiedScan.STATUSES,
        "outcomes": UnidentifiedScan.OUTCOMES,
        "kinds": UnidentifiedScan.KINDS,
        "new_count": UnidentifiedScan.objects.filter(status=UnidentifiedScan.NEW).count(),
        "filters": {"status": status, "outcome": outcome, "kind": kind, "q": q,
                    "from": request.GET.get("from", ""), "to": request.GET.get("to", "")},
        "querystring": params.urlencode(),
    })


@gate
def scan_detail(request, pk):
    scan = get_object_or_404(UnidentifiedScan, pk=pk)
    form = ReviewForm(request.POST or None, instance=scan)
    if request.method == "POST" and form.is_valid():
        if not form.has_changed():
            messages.info(request, "No changes to save.")
            return redirect("unidentified_scan_detail", pk=scan.pk)
        scan = form.save(commit=False)
        scan.reviewed_by = request.user
        scan.reviewed_at = timezone.now()
        scan.save()
        what = scan.identified_as or scan.get_kind_display() or "—"
        log_action(request.user, AuditLog.UPDATE, record_type=RECORD_TYPE,
                   details=f"#{scan.pk} {scan.get_status_display()}: {what}", request=request)
        messages.success(request, f"Scan #{scan.pk} was saved.")
        return redirect("unidentified_scan_list")
    return render(request, "portal/unidentified_scan_detail.html",
                  {"role": get_role(request.user), "scan": scan, "form": form})


@gate
def scan_delete(request, pk):
    """Delete the scan and its photo straight away (e.g. it shows a person)."""
    scan = get_object_or_404(UnidentifiedScan, pk=pk)
    if request.method != "POST":
        return redirect("unidentified_scan_detail", pk=scan.pk)
    photo_name = scan.photo.name
    scan.delete()
    scan.photo.storage.delete(photo_name)
    log_action(request.user, AuditLog.DELETE, record_type=RECORD_TYPE,
               details=f"#{pk}", request=request)
    messages.success(request, f"Scan #{pk} and its photo were deleted.")
    return redirect("unidentified_scan_list")
