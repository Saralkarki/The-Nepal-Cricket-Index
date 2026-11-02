from django.test import TestCase

# Create your tests here.
from django.test import SimpleTestCase
from django.urls import reverse


class HomepageTests(SimpleTestCase):
    def test_homepage_renders_with_default_season(self):
        response = self.client.get(reverse("cricket_nepal:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The story of Nepal cricket")
        self.assertContains(response, "NPL Season 2 (2025)")
        self.assertEqual(response.context["selected_year"], "2025")

    def test_season_selector_accepts_supported_season(self):
        response = self.client.get(reverse("cricket_nepal:home"), {"season": "2024"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_year"], "2024")
        self.assertContains(response, "Season 1 · 2024")

    def test_invalid_season_falls_back_to_latest_supported_season(self):
        response = self.client.get(reverse("cricket_nepal:home"), {"season": "invalid"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_year"], "2025")
