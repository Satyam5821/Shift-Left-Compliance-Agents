import unittest

from app.services import github_apply


class TestIdempotentInsert(unittest.TestCase):
    def test_insert_is_idempotent_when_chunk_already_present(self):
        original = (
            "package x;\n"
            "\n"
            "public class A {\n"
            "  private static final org.slf4j.Logger logger = org.slf4j.LoggerFactory.getLogger(A.class);\n"
            "\n"
            "  public void m() {\n"
            "    System.out.println(\"x\");\n"
            "  }\n"
            "}\n"
        )
        chunk = "  private static final org.slf4j.Logger logger = org.slf4j.LoggerFactory.getLogger(A.class);\n"
        ok, new_text, reason = github_apply._apply_insert_text(
            original,
            mode="insert_before",
            line=None,
            anchor="  public void m() {",
            new_code=chunk,
        )
        self.assertFalse(ok)
        self.assertEqual(original, new_text)
        self.assertIn("safe-skip", reason)


if __name__ == "__main__":
    unittest.main()

