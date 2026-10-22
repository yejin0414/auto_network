"""계정 하나(백본·MM·WLC 공통), enable 비밀번호 미사용."""
import json
import tempfile
import unittest
from pathlib import Path

from nc.config import CREDENTIAL_PROFILES, validate
from nc.credentials import Credential, CredentialStore


class SharedAccount(unittest.TestCase):
    def test_one_profile_for_all_devices(self):
        self.assertEqual(list(CREDENTIAL_PROFILES), ["shared"])
        cfg = validate({"devices": [{"role": "BB", "host": "192.0.2.101", "credential": "backbone"},
                                    {"role": "WLC", "host": "192.0.2.102", "credential": "aruba"},
                                    {"role": "MM", "host": "192.0.2.103"}]})
        self.assertEqual({d["credential"] for d in cfg["devices"]}, {"shared"})

    def test_any_old_name_is_the_same_account_and_no_secret(self):
        c = CredentialStore(persistent=False)
        c.set("aruba", Credential("op", "pw", "enable-secret"), False)
        self.assertEqual(c.get("backbone").username, "op")
        self.assertEqual(c.get("shared").secret, "")
        self.assertEqual(list(c.status()), ["shared"])


if __name__ == "__main__":
    unittest.main()
