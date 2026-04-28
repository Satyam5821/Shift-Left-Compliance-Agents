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

    def test_java_constant_insert_skips_if_name_already_defined(self):
        original = (
            "public class A {\n"
            "  private static final String ERROR_READING_FILE_MESSAGE = \"Error reading file: \";\n"
            "  public void m() {}\n"
            "}\n"
        )
        # This mimics the agent inserting multiple constants, including one that already exists.
        chunk = (
            "  private static final String EMPLOYEE_NOT_FOUND_MESSAGE = \"Employee not found for ID: \";\n"
            "  private static final String ERROR_READING_FILE_MESSAGE = \"Error reading file: \";\n"
        )
        ok, new_text, reason = github_apply._apply_insert_text(
            original,
            mode="insert_before",
            line=None,
            anchor="  public void m() {}",
            new_code=chunk,
        )
        self.assertFalse(ok)
        self.assertEqual(original, new_text)
        self.assertIn("ERROR_READING_FILE_MESSAGE", reason)

    def test_java_sanity_rejects_duplicate_constant_names(self):
        # Even if an insert slips through, the final safety check should refuse
        # to write a .java file that contains duplicate constant names.
        broken = (
            "public class A {\n"
            "  private static final String ERROR_READING_FILE_MESSAGE = \"Error reading file: \";\n"
            "  private static final String ERROR_READING_FILE_MESSAGE = \"Error reading file: \";\n"
            "}\n"
        )
        err = github_apply._java_quick_sanity(broken)
        self.assertIsNotNone(err)
        self.assertIn("duplicate constant name", err or "")


if __name__ == "__main__":
    unittest.main()

