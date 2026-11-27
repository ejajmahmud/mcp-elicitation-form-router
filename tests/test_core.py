"""Tests for MCP Elicitation Form Router."""
import unittest
from mcp_elicitation_form_router.core import (
    ElicitationError,
    ElicitationFormBuilder,
    ElicitationRouter,
    validate_elicitation_content,
)


class TestMCPElicitationRouter(unittest.TestCase):
    def _build_schema(self):
        return (
            ElicitationFormBuilder()
            .add_string("email", title="Owner Email", fmt="email", required=True)
            .add_string("tier", title="Tier", enum=["free", "pro"], default="free")
            .add_integer("seats", title="Seats", minimum=1, maximum=50, default=5)
            .add_boolean("notify", title="Notify", default=True)
            .build()
        )

    def test_valid_submission_and_default_merge(self):
        schema = self._build_schema()
        router = ElicitationRouter()
        router.create_request("r1", "Enter billing info", schema, ttl_seconds=60.0, now=100.0)
        res = router.submit_response("r1", "accept", {"email": "dev@example.com"}, now=110.0)
        self.assertEqual(res.state, "accepted")
        self.assertEqual(res.merged_content, {"email": "dev@example.com", "tier": "free", "seats": 5, "notify": True})

    def test_strict_type_and_range_validation(self):
        schema = self._build_schema()
        with self.assertRaises(ElicitationError):
            validate_elicitation_content(schema, {"email": "dev@example.com", "seats": True})
        with self.assertRaises(ElicitationError):
            validate_elicitation_content(schema, {"email": "dev@example.com", "seats": 99})
        with self.assertRaises(ElicitationError):
            validate_elicitation_content(schema, {"email": "not-an-email"})
        with self.assertRaises(ElicitationError):
            validate_elicitation_content(schema, {"email": "dev@example.com", "extra": 1})

    def test_timeout_fsm_and_double_submit_rejection(self):
        schema = self._build_schema()
        router = ElicitationRouter()
        router.create_request("r-exp", "Timed prompt", schema, ttl_seconds=10.0, now=100.0)
        expired = router.expire_stale(now=115.0)
        self.assertEqual(expired, ["r-exp"])
        self.assertEqual(router.get_state("r-exp"), "timed_out")
        with self.assertRaises(ElicitationError):
            router.submit_response("r-exp", "accept", {"email": "a@b.com"}, now=116.0)

    def test_decline_and_cancel_states(self):
        schema = self._build_schema()
        router = ElicitationRouter()
        router.create_request("r-dec", "Confirm", schema, now=10.0)
        r_dec = router.submit_response("r-dec", "decline", now=12.0)
        self.assertEqual(r_dec.state, "declined")
        self.assertIsNone(r_dec.merged_content)
        router.create_request("r-can", "Confirm", schema, now=10.0)
        r_can = router.submit_response("r-can", "cancel", now=12.0)
        self.assertEqual(r_can.state, "cancelled")
