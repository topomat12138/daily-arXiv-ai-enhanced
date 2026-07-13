import unittest

from ai.structure import Structure


class StructureTests(unittest.TestCase):
    def test_accepts_list_fields(self):
        result = Structure(
            tldr="Concise result",
            method="Main method",
            tags=["topological superconductivity", "Josephson physics"],
            specific_terms=["planar Josephson junction", "Andreev bound state"],
        )

        self.assertEqual(
            result.tags,
            ["topological superconductivity", "Josephson physics"],
        )
        self.assertEqual(
            result.specific_terms,
            ["planar Josephson junction", "Andreev bound state"],
        )

    def test_normalizes_legacy_separated_strings(self):
        result = Structure(
            tldr="Concise result",
            method="Main method",
            tags="topological superconductivity, Josephson physics；quantum geometry",
            specific_terms="planar Josephson junction; Andreev bound state、phase bias",
        )

        self.assertEqual(
            result.tags,
            ["topological superconductivity", "Josephson physics", "quantum geometry"],
        )
        self.assertEqual(
            result.specific_terms,
            ["planar Josephson junction", "Andreev bound state", "phase bias"],
        )

    def test_trims_drops_empty_and_deduplicates_case_insensitively(self):
        result = Structure(
            tldr="Concise result",
            method="Main method",
            tags=["  Vortex Physics ", "", "vortex physics", "Quantum Geometry"],
            specific_terms=" Andreev bound state, , ANDREEV BOUND STATE； phase bias ",
        )

        self.assertEqual(result.tags, ["Vortex Physics", "Quantum Geometry"])
        self.assertEqual(result.specific_terms, ["Andreev bound state", "phase bias"])

    def test_null_lists_become_empty_lists(self):
        result = Structure(
            tldr="Concise result",
            method="Main method",
            tags=None,
            specific_terms=None,
        )

        self.assertEqual(result.tags, [])
        self.assertEqual(result.specific_terms, [])


if __name__ == "__main__":
    unittest.main()
