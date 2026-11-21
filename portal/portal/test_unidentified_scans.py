"""
Tests for unidentified scans: saved by /api/identify, reviewed in the portal, purged after 90 days.

Run with:   python manage.py test
"""
import io
import os
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from PIL import Image

from .models import AuditLog, StoredFile, UnidentifiedScan

PW = "ChangeMe123!"


def jpeg_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "pink").save(buf, "JPEG")
    return buf.getvalue()


def photo():
    return SimpleUploadedFile("flower.jpg", jpeg_bytes(), content_type="image/jpeg")


def make_scan(**kw):
    scan = UnidentifiedScan(**kw)
    scan.photo.save("scan.jpg", ContentFile(jpeg_bytes()), save=True)
    return scan


class SavedByIdentifyTests(TestCase):
    def setUp(self):
        call_command("seed_roles", verbosity=0)
        self.visitor = User.objects.create_user("vivi", password="secret1")

    @mock.patch("portal.api.classifier.available", return_value=True)
    @mock.patch("portal.api.classifier.classify", return_value=[("costus", 0.35), ("calathea", 0.30)])
    def test_no_match_saves_photo_with_visitor_and_model_guess(self, _c, _a):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PLANTNET_API_KEY", None)
            r = self.client.post("/api/identify", {"image": photo(), "userId": str(self.visitor.pk)})
        self.assertEqual(r.json()["results"], [])
        scan = UnidentifiedScan.objects.get()
        self.assertEqual(scan.visitor_username, "vivi")
        self.assertEqual(scan.outcome, UnidentifiedScan.NO_MATCH)
        self.assertEqual(scan.model_label, "costus")
        self.assertAlmostEqual(scan.model_score, 0.35)
        self.assertEqual(scan.status, UnidentifiedScan.NEW)
        self.assertTrue(StoredFile.objects.filter(name=scan.photo.name).exists())
        self.assertEqual(bytes(StoredFile.objects.get(name=scan.photo.name).content)[:2], b"\xff\xd8")

    @mock.patch.dict(os.environ, {"PLANTNET_API_KEY": "test-key"})
    @mock.patch("portal.api.classifier.available", return_value=False)
    @mock.patch("portal.api.requests.post")
    def test_plantnet_suggestion_is_saved_with_its_name(self, fake_post, _a):
        fake_post.return_value = mock.Mock(status_code=200, ok=True, json=lambda: {"results": [
            {"species": {"scientificNameWithoutAuthor": "Chrysanthemum morifolium",
                         "commonNames": ["Florist's daisy"]}}]})
        self.client.post("/api/identify", {"image": photo()})
        scan = UnidentifiedScan.objects.get()
        self.assertEqual(scan.outcome, UnidentifiedScan.SUGGESTION)
        self.assertEqual(scan.suggested_name, "Florist's daisy")
        self.assertEqual(scan.visitor_username, "")

    @mock.patch.dict(os.environ, {"PLANTNET_API_KEY": "test-key"})
    @mock.patch("portal.api.classifier.available", return_value=False)
    @mock.patch("portal.api.requests.post")
    def test_plantnet_not_found_is_saved_as_no_match(self, fake_post, _a):
        fake_post.return_value = mock.Mock(status_code=404, ok=False)
        self.client.post("/api/identify", {"image": photo()})
        self.assertEqual(UnidentifiedScan.objects.get().outcome, UnidentifiedScan.NO_MATCH)

    @mock.patch("portal.api.classifier.available", return_value=True)
    @mock.patch("portal.api.classifier.classify", return_value=[("tanglin_gate", 0.93)])
    def test_confident_label_without_a_card_is_saved_as_suggestion(self, _c, _a):
        self.client.post("/api/identify", {"image": photo()})
        scan = UnidentifiedScan.objects.get()
        self.assertEqual(scan.outcome, UnidentifiedScan.SUGGESTION)
        self.assertEqual(scan.suggested_name, "Tanglin Gate")

    @mock.patch.dict(os.environ, {"PLANTNET_API_KEY": "test-key"})
    @mock.patch("portal.api.classifier.available", return_value=False)
    @mock.patch("portal.api.requests.post")
    def test_plantnet_error_saves_nothing(self, fake_post, _a):
        fake_post.return_value = mock.Mock(status_code=500, ok=False)
        self.assertEqual(self.client.post("/api/identify", {"image": photo()}).status_code, 502)
        self.assertFalse(UnidentifiedScan.objects.exists())

    @mock.patch("portal.api.classifier.available", return_value=True)
    @mock.patch("portal.api.classifier.classify", return_value=[("costus", 0.35)])
    @mock.patch("portal.api.UnidentifiedScan.save", side_effect=RuntimeError("db down"))
    def test_saving_failure_does_not_break_the_scan(self, _save, _c, _a):
        os.environ.pop("PLANTNET_API_KEY", None)
        r = self.client.post("/api/identify", {"image": photo()})
        self.assertEqual(r.status_code, 200)


class ReviewPageTests(TestCase):
    def setUp(self):
        call_command("seed_roles", verbosity=0)
        self.scan = make_scan(visitor_username="vivi", model_label="costus", model_score=0.4)

    def login(self, username):
        self.client.login(username=username, password=PW)

    def test_researcher_and_sysadmin_can_open_user_admin_cannot(self):
        for user, code in [("researcher", 200), ("sysadmin", 200), ("useradmin", 403)]:
            self.client.logout()
            self.login(user)
            self.assertEqual(self.client.get("/section/unidentified-scans/").status_code, code, user)

    def test_list_shows_scan_and_filters(self):
        self.login("researcher")
        r = self.client.get("/section/unidentified-scans/")
        self.assertContains(r, "vivi")
        self.assertContains(r, "1 waiting for review")
        r = self.client.get("/section/unidentified-scans/?status=LABELLED")
        self.assertContains(r, "No unidentified scans found.")

    def test_review_labels_scan_and_writes_audit(self):
        self.login("researcher")
        r = self.client.post(f"/section/unidentified-scans/{self.scan.pk}/", {
            "status": "LABELLED", "kind": "PLANT", "identified_as": "Chrysanthemum", "notes": ""})
        self.assertRedirects(r, "/section/unidentified-scans/")
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.identified_as, "Chrysanthemum")
        self.assertEqual(self.scan.reviewed_by.username, "researcher")
        self.assertTrue(AuditLog.objects.filter(record_type="Unidentified Scan",
                                                action=AuditLog.UPDATE).exists())

    def test_labelled_needs_kind(self):
        self.login("researcher")
        r = self.client.post(f"/section/unidentified-scans/{self.scan.pk}/",
                             {"status": "LABELLED", "kind": "", "identified_as": "", "notes": ""})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Choose what the photo shows")

    def test_delete_removes_scan_and_photo(self):
        self.login("researcher")
        name = self.scan.photo.name
        self.assertEqual(self.client.get(f"/section/unidentified-scans/{self.scan.pk}/delete/").status_code, 302)
        self.assertTrue(UnidentifiedScan.objects.exists())          # GET does not delete
        self.client.post(f"/section/unidentified-scans/{self.scan.pk}/delete/")
        self.assertFalse(UnidentifiedScan.objects.exists())
        self.assertFalse(StoredFile.objects.filter(name=name).exists())


class PurgeTests(TestCase):
    def test_purges_only_old_scans_and_their_photos(self):
        old = make_scan()
        UnidentifiedScan.objects.filter(pk=old.pk).update(scanned_at=timezone.now() - timedelta(days=91))
        recent = make_scan()

        call_command("purge_unidentified_scans", "--dry-run", stdout=io.StringIO())
        self.assertEqual(UnidentifiedScan.objects.count(), 2)

        call_command("purge_unidentified_scans", stdout=io.StringIO())
        self.assertEqual(list(UnidentifiedScan.objects.all()), [recent])
        self.assertFalse(StoredFile.objects.filter(name=old.photo.name).exists())
        self.assertTrue(StoredFile.objects.filter(name=recent.photo.name).exists())
