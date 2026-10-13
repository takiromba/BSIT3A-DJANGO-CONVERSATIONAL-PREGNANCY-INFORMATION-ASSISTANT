"""Tests for the superuser-only user-management endpoints.

Covers the authorization matrix (anonymous / regular user / staff-but-not-superuser /
superuser), the AJAX list envelope, single-user fetch, create/update validation and
password handling, and deletion rules.
"""

from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

PASSWORD = "secret1234"

LIST_FIELDS = {
    "id",
    "username",
    "first_name",
    "last_name",
    "email",
    "is_staff",
    "is_active",
    "date_joined",
}
DETAIL_FIELDS = LIST_FIELDS - {"date_joined"}


class UserAjaxTestMixin:
    """Shared fixtures: one superuser, one staff member, one regular member."""

    @staticmethod
    def _redirect_path(response):
        """Path of the redirect target, ignoring any ?next= query parameter."""
        return urlsplit(response.url).path

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=PASSWORD,
        )
        cls.staff_member = User.objects.create_user(
            username="staff-member",
            email="staff@example.com",
            password=PASSWORD,
            is_staff=True,
        )
        cls.member = User.objects.create_user(
            username="plain-member",
            email="member@example.com",
            password=PASSWORD,
        )


class AnonymousAccessTests(UserAjaxTestMixin, TestCase):
    """Unauthenticated requests must never reach the endpoints or leak data."""

    def _assert_redirects_to_login(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._redirect_path(response), reverse("login"))

    def test_list_page_redirects_to_login(self):
        self._assert_redirects_to_login(self.client.get(reverse("users:user_list")))

    def test_list_ajax_redirects_to_login(self):
        self._assert_redirects_to_login(
            self.client.get(reverse("users:user_list_ajax"))
        )

    def test_get_ajax_redirects_to_login_without_touching_the_database(self):
        self._assert_redirects_to_login(
            self.client.get(reverse("users:user_get_ajax", args=[self.member.pk]))
        )

    def test_save_ajax_redirects_to_login_and_creates_nothing(self):
        before = User.objects.count()
        self._assert_redirects_to_login(
            self.client.post(
                reverse("users:user_save_ajax"),
                {"username": "ghost", "password": PASSWORD},
            )
        )
        self.assertEqual(User.objects.count(), before)

    def test_delete_ajax_redirects_to_login_and_deletes_nothing(self):
        self._assert_redirects_to_login(
            self.client.post(reverse("users:user_delete_ajax", args=[self.member.pk]))
        )
        self.assertTrue(User.objects.filter(pk=self.member.pk).exists())


class NonSuperuserAccessTests(UserAjaxTestMixin, TestCase):
    """Regular users (even staff) get bounced to the dashboard with no data."""

    def setUp(self):
        # Logged in as staff but NOT superuser — the subtlest privilege case.
        self.client.force_login(self.staff_member)

    def _assert_redirects_to_dashboard(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._redirect_path(response), reverse("dashboard"))

    def test_list_page_redirects_to_dashboard(self):
        self._assert_redirects_to_dashboard(self.client.get(reverse("users:user_list")))

    def test_list_ajax_redirects_to_dashboard(self):
        self._assert_redirects_to_dashboard(
            self.client.get(reverse("users:user_list_ajax"))
        )

    def test_get_ajax_redirects_without_leaking_other_users(self):
        response = self.client.get(
            reverse("users:user_get_ajax", args=[self.superuser.pk])
        )
        self._assert_redirects_to_dashboard(response)
        self.assertNotIn("admin", response.content.decode())

    def test_save_ajax_redirects_and_creates_nothing(self):
        before = User.objects.count()
        response = self.client.post(
            reverse("users:user_save_ajax"),
            {"username": "sneaky", "password": PASSWORD, "is_staff": "true"},
        )
        self._assert_redirects_to_dashboard(response)
        self.assertEqual(User.objects.count(), before)

    def test_save_ajax_cannot_promote_the_requesting_user(self):
        response = self.client.post(
            reverse("users:user_save_ajax"),
            {
                "id": str(self.staff_member.pk),
                "username": self.staff_member.username,
                "is_staff": "true",
                "is_active": "true",
            },
        )
        self._assert_redirects_to_dashboard(response)
        self.staff_member.refresh_from_db()
        self.assertFalse(self.staff_member.is_superuser)

    def test_delete_ajax_redirects_and_deletes_nothing(self):
        response = self.client.post(
            reverse("users:user_delete_ajax", args=[self.superuser.pk])
        )
        self._assert_redirects_to_dashboard(response)
        self.assertTrue(User.objects.filter(pk=self.superuser.pk).exists())


class UserListAjaxTests(UserAjaxTestMixin, TestCase):

    def setUp(self):
        self.client.force_login(self.superuser)

    def test_returns_pagination_envelope(self):
        response = self.client.get(reverse("users:user_list_ajax"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            set(payload),
            {"data", "has_next", "has_prev", "page", "pages", "total"},
        )
        self.assertEqual(payload["total"], User.objects.count())
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["pages"], 1)
        self.assertFalse(payload["has_next"])
        self.assertFalse(payload["has_prev"])

    def test_rows_contain_only_public_fields(self):
        response = self.client.get(reverse("users:user_list_ajax"))

        rows = response.json()["data"]
        self.assertEqual(len(rows), User.objects.count())
        for row in rows:
            self.assertEqual(set(row), LIST_FIELDS)

    def test_response_never_exposes_password_material(self):
        response = self.client.get(reverse("users:user_list_ajax"))

        body = response.content.decode()
        self.assertNotIn(PASSWORD, body)
        self.assertNotIn("password", body)

    def test_orders_users_by_date_joined_descending(self):
        response = self.client.get(reverse("users:user_list_ajax"))

        expected = list(
            User.objects.order_by("-date_joined").values_list("username", flat=True)
        )
        actual = [row["username"] for row in response.json()["data"]]
        self.assertEqual(actual, expected)

    def test_paginates_results(self):
        for i in range(10):
            User.objects.create_user(username=f"bulk-user-{i:02d}", password=PASSWORD)

        page1 = self.client.get(reverse("users:user_list_ajax")).json()
        self.assertEqual(page1["total"], 13)
        self.assertEqual(page1["pages"], 2)
        self.assertEqual(len(page1["data"]), 10)
        self.assertTrue(page1["has_next"])
        self.assertFalse(page1["has_prev"])

        page2 = self.client.get(reverse("users:user_list_ajax"), {"page": 2}).json()
        self.assertEqual(page2["page"], 2)
        self.assertEqual(len(page2["data"]), 3)
        self.assertFalse(page2["has_next"])
        self.assertTrue(page2["has_prev"])

    def test_out_of_range_page_clamps_to_last_page(self):
        for i in range(10):
            User.objects.create_user(username=f"clamp-user-{i:02d}", password=PASSWORD)

        response = self.client.get(reverse("users:user_list_ajax"), {"page": 99})

        payload = response.json()
        self.assertEqual(payload["pages"], 2)
        self.assertEqual(payload["page"], 2)
        self.assertTrue(payload["has_prev"])
        self.assertFalse(payload["has_next"])


class UserGetAjaxTests(UserAjaxTestMixin, TestCase):

    def setUp(self):
        self.client.force_login(self.superuser)

    def test_returns_detail_fields(self):
        response = self.client.get(
            reverse("users:user_get_ajax", args=[self.member.pk])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(payload), DETAIL_FIELDS)
        self.assertEqual(payload["username"], self.member.username)
        self.assertEqual(payload["email"], self.member.email)
        self.assertFalse(payload["is_staff"])
        self.assertTrue(payload["is_active"])

    def test_unknown_pk_returns_404(self):
        response = self.client.get(reverse("users:user_get_ajax", args=[999999]))

        self.assertEqual(response.status_code, 404)

    def test_response_never_exposes_password_material(self):
        response = self.client.get(
            reverse("users:user_get_ajax", args=[self.member.pk])
        )

        body = response.content.decode()
        self.assertNotIn(PASSWORD, body)
        self.assertNotIn("password", body)


class UserSaveAjaxCreateTests(UserAjaxTestMixin, TestCase):

    def setUp(self):
        self.client.force_login(self.superuser)
        self.url = reverse("users:user_save_ajax")

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_creates_user_with_hashed_password(self):
        response = self.client.post(
            self.url,
            {
                "username": "new-parent",
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "jane@example.com",
                "password": PASSWORD,
                "is_staff": "true",
                "is_active": "true",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertNotIn("password", payload)

        created = User.objects.get(pk=payload["id"])
        self.assertEqual(created.username, "new-parent")
        self.assertEqual(created.first_name, "Jane")
        self.assertEqual(created.last_name, "Doe")
        self.assertEqual(created.email, "jane@example.com")
        self.assertTrue(created.is_staff)
        self.assertTrue(created.is_active)
        self.assertTrue(created.check_password(PASSWORD))
        self.assertNotIn(PASSWORD, created.password)

    def test_username_is_stripped(self):
        response = self.client.post(
            self.url,
            {
                "username": "  padded  ",
                "password": PASSWORD,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "padded")

    def test_missing_username_is_rejected(self):
        before = User.objects.count()
        response = self.client.post(self.url, {"password": PASSWORD})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Username is required.")
        self.assertEqual(User.objects.count(), before)

    def test_blank_username_is_rejected(self):
        response = self.client.post(self.url, {"username": "   ", "password": PASSWORD})

        self.assertEqual(response.status_code, 400)

    def test_missing_password_is_rejected(self):
        before = User.objects.count()
        response = self.client.post(self.url, {"username": "no-password"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Password is required for new users.",
        )
        self.assertEqual(User.objects.count(), before)

    def test_blank_password_is_rejected(self):
        response = self.client.post(
            self.url, {"username": "no-password", "password": ""}
        )

        self.assertEqual(response.status_code, 400)

    def test_duplicate_username_is_rejected(self):
        before = User.objects.count()
        response = self.client.post(
            self.url,
            {
                "username": self.member.username,
                "password": PASSWORD,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "That username is already taken.")
        self.assertEqual(User.objects.count(), before)

    def test_duplicate_email_is_rejected(self):
        before = User.objects.count()
        response = self.client.post(
            self.url,
            {
                "username": "email-clash",
                "email": self.member.email,
                "password": PASSWORD,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "That email is already in use.")
        self.assertEqual(User.objects.count(), before)

    def test_flags_are_false_unless_exactly_true(self):
        response = self.client.post(
            self.url,
            {
                "username": "flag-parsing",
                "password": PASSWORD,
                "is_staff": "True",
                "is_active": "1",
            },
        )

        created = User.objects.get(pk=response.json()["id"])
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_active)

    def test_new_user_is_usable_for_login(self):
        self.client.post(
            self.url,
            {
                "username": "fresh-login",
                "password": PASSWORD,
            },
        )

        self.assertTrue(
            User.objects.get(username="fresh-login").check_password(PASSWORD)
        )


class UserSaveAjaxUpdateTests(UserAjaxTestMixin, TestCase):

    def setUp(self):
        self.client.force_login(self.superuser)
        self.url = reverse("users:user_save_ajax")
        self.target = User.objects.create_user(
            username="target",
            email="target@example.com",
            password=PASSWORD,
        )

    def _post(self, **overrides):
        data = {
            "id": str(self.target.pk),
            "username": self.target.username,
            "email": self.target.email,
            "is_staff": "true",
            "is_active": "true",
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_updates_fields(self):
        response = self._post(
            first_name="Renamed", last_name="Person", email="renamed@example.com"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, "Renamed")
        self.assertEqual(self.target.last_name, "Person")
        self.assertEqual(self.target.email, "renamed@example.com")
        self.assertTrue(self.target.is_staff)

    def test_blank_password_leaves_the_hash_untouched(self):
        original_hash = self.target.password

        response = self._post(password="")

        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.password, original_hash)
        self.assertTrue(self.target.check_password(PASSWORD))

    def test_provided_password_is_rehashed(self):
        response = self._post(password="brand-new-pass")

        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("brand-new-pass"))
        self.assertFalse(self.target.check_password(PASSWORD))

    def test_updating_keeps_own_username_and_email(self):
        response = self._post(username=self.target.username, email=self.target.email)

        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.username, "target")

    def test_conflicting_username_is_rejected(self):
        original_username = self.target.username

        response = self._post(username=self.member.username)

        self.assertEqual(response.status_code, 400)
        self.target.refresh_from_db()
        self.assertEqual(self.target.username, original_username)

    def test_conflicting_email_is_rejected(self):
        original_email = self.target.email

        response = self._post(email=self.member.email)

        self.assertEqual(response.status_code, 400)
        self.target.refresh_from_db()
        self.assertEqual(self.target.email, original_email)

    def test_missing_user_returns_404(self):
        response = self.client.post(self.url, {"id": "999999", "username": "nobody"})

        self.assertEqual(response.status_code, 404)

    def test_flags_can_be_revoked(self):
        self._post(is_staff="true", is_active="true")
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_staff)

        self._post(is_staff="false", is_active="false")
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_staff)
        self.assertFalse(self.target.is_active)

    def test_response_never_exposes_password_material(self):
        response = self._post(password=PASSWORD)

        body = response.content.decode()
        self.assertNotIn("password", body)


class UserDeleteAjaxTests(UserAjaxTestMixin, TestCase):

    def setUp(self):
        self.client.force_login(self.superuser)
        self.target = User.objects.create_user(
            username="deletable",
            email="deletable@example.com",
            password=PASSWORD,
        )

    def test_get_is_not_allowed(self):
        response = self.client.get(
            reverse("users:user_delete_ajax", args=[self.target.pk])
        )

        self.assertEqual(response.status_code, 405)
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists())

    def test_deletes_the_target_user(self):
        response = self.client.post(
            reverse("users:user_delete_ajax", args=[self.target.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "deleted"})
        self.assertFalse(User.objects.filter(pk=self.target.pk).exists())

    def test_unknown_pk_returns_404(self):
        response = self.client.post(reverse("users:user_delete_ajax", args=[999999]))

        self.assertEqual(response.status_code, 404)

    def test_superuser_cannot_delete_themselves(self):
        response = self.client.post(
            reverse("users:user_delete_ajax", args=[self.superuser.pk])
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "You cannot delete yourself")
        self.assertTrue(User.objects.filter(pk=self.superuser.pk).exists())


class KnownImplementationGapsTests(UserAjaxTestMixin, TestCase):
    """Regression tests for previously reported user-management bugs."""

    def setUp(self):
        self.client.force_login(self.superuser)

    def test_list_ajax_should_apply_the_search_query(self):
        # The HTML page filters on ?q= but the AJAX list ignores it entirely.
        User.objects.create_user(username="needle-user", password=PASSWORD)
        User.objects.create_user(username="haystack-user", password=PASSWORD)

        payload = self.client.get(
            reverse("users:user_list_ajax"), {"q": "needle"}
        ).json()

        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["data"][0]["username"], "needle-user")

    def test_save_ajax_should_reject_a_malformed_user_id(self):
        # get_object_or_404(User, pk='abc') raises ValueError -> 500, not 400.
        response = self.client.post(
            reverse("users:user_save_ajax"),
            {"id": "abc", "username": "anything", "password": PASSWORD},
        )

        self.assertEqual(response.status_code, 400)
