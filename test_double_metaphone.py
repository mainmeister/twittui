"""Unit tests for Double Metaphone phonetic algorithm (canonical test vectors)."""

import unittest

from double_metaphone import double_metaphone, get_phonetic_keys


class TestDoubleMetaphone(unittest.TestCase):
    """Verify Lawrence Philips' Double Metaphone rules and regression fixes."""

    def test_empty_and_non_alpha(self) -> None:
        self.assertEqual(double_metaphone(""), ("", ""))
        self.assertEqual(double_metaphone("   "), ("", ""))
        self.assertEqual(double_metaphone("12345!@#"), ("", ""))

    def test_cedilla_and_enye_preserved(self) -> None:
        # Bug #9.1: Ç and Ñ must not be stripped before encoding
        self.assertEqual(double_metaphone("GARÇON"), ("KRSN", "KRSN"))
        self.assertEqual(double_metaphone("PIÑATA"), ("PNT", "PNT"))
        keys = get_phonetic_keys("Garçon eats a Piñata")
        self.assertIn("KRSN", keys)
        self.assertIn("PNT", keys)

    def test_space_and_padding_boundary_rules_reachable(self) -> None:
        # Bug #9.1: 'VAN ', 'VON ', 'SAN ', trailing ' ' ('BACH'), 'IER ', 'JOSE '
        self.assertEqual(double_metaphone("BACH"), ("PK", "PK"))
        self.assertEqual(double_metaphone("JOSE"), ("HS", "HS"))
        self.assertEqual(double_metaphone("SAN JOSE"), ("SNHS", "SNHS"))
        # French -IER drops final R in primary ('RJ') and keeps it in secondary ('RJR')
        self.assertEqual(double_metaphone("ROGIER"), ("RJ", "RJR"))
        self.assertEqual(double_metaphone("VAN THORN"), ("FNTR", "FNTR"))

    def test_th_and_tch_encoding(self) -> None:
        # Bug #9.2: TH -> ('0', 'T') (except THOMAS/VAN/VON/SCH), TCH -> ('X', 'X')
        self.assertEqual(double_metaphone("THE"), ("0", "T"))
        self.assertEqual(double_metaphone("THINK"), ("0NK", "TNK"))
        self.assertEqual(double_metaphone("THOMAS"), ("TMS", "TMS"))
        self.assertEqual(double_metaphone("MATCH"), ("MX", "MX"))
        self.assertEqual(double_metaphone("WITCH"), ("AX", "FX"))

    def test_sch_encoding(self) -> None:
        # Bug #9.4: SCHOOL/SCHOONER secondary must be SK (not KK); SCHENKER primary X / secondary SK
        self.assertEqual(double_metaphone("SCHOOL"), ("SKL", "SKL"))
        self.assertEqual(double_metaphone("SCHOONER"), ("SKNR", "SKNR"))
        self.assertEqual(double_metaphone("SCHENKER"), ("XNKR", "SKNK"))

    def test_aggi_ggi_dg_gn_gli_and_wicz_rules(self) -> None:
        # Bug #9.3 & #9.5
        self.assertEqual(double_metaphone("BAGGIO"), ("PJ", "PK"))
        self.assertEqual(double_metaphone("AGGI"), ("AJ", "AK"))
        self.assertEqual(double_metaphone("EDGAR"), ("ATKR", "ATKR"))
        self.assertEqual(double_metaphone("EDGE"), ("AJ", "AJ"))
        self.assertEqual(double_metaphone("SIGN"), ("SN", "SKN"))
        self.assertEqual(double_metaphone("COGNAC"), ("KNK", "KKNK"))
        self.assertEqual(double_metaphone("AGNOSTIC"), ("AKNS", "ANST"))
        self.assertEqual(double_metaphone("TAGLIARO"), ("TKLR", "TLR"))
        self.assertEqual(double_metaphone("LEWITZ"), ("LTS", "LFX"))

    def test_twit_host_name_phonetic_matching(self) -> None:
        # Ensure existing TWiT phonetic search pairs remain equivalent
        self.assertEqual(double_metaphone("ballacer"), double_metaphone("Ballecer"))
        # Canonical Double Metaphone pair: Smith ('SM0', 'XMT') overlaps Schmidt ('XMT', 'SMT') on 'XMT'
        self.assertTrue(set(double_metaphone("Smith")) & set(double_metaphone("Schmidt")))


if __name__ == "__main__":
    unittest.main()
