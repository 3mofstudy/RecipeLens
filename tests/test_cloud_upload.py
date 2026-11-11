"""驗證本機轉檔、格式選擇及部分上傳失敗後的重試，不存取 Google。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

from httplib2 import Response
from googleapiclient.errors import HttpError
from PIL import Image

from src.cloud_upload import destination_folder, list_folders, upload_files, upload_recipe
from src.document_export import export_documents
from src.local_storage import read_json


class CloudUploadTests(unittest.TestCase):
    def test_cloud_only_docx_is_staged_separately_from_local_files(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder).resolve() / "食譜.md"
            source.write_text("# 測試食譜", encoding="utf-8")
            with patch("src.cloud_upload.upload_files", return_value=[]) as upload:
                upload_recipe(source, ("md", "docx"), service=MagicMock(),
                              progress=lambda _: None, stage_missing=True)
            staged = source.parent / ".drive" / "documents" / "食譜.docx"
            self.assertTrue(staged.is_file())
            self.assertFalse(source.with_suffix(".docx").exists())
            self.assertEqual(upload.call_args.args[0], [source, staged])

    def test_docx_accepts_jpeg_without_jfif_header(self):
        from docx import Document
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "step.jpg"
            Image.new("RGB", (80, 60), "white").save(image)
            data = image.read_bytes()
            self.assertEqual(data[2:4], b"\xff\xe0")
            # 移除 APP0/JFIF 區塊，模擬 FFmpeg 產生的有效 JPEG。
            length = int.from_bytes(data[4:6], "big")
            image.write_bytes(data[:2] + data[4 + length:])
            original = image.read_bytes()
            source = root / "食譜.md"
            source.write_text("# 測試食譜\n\n![步驟](step.jpg)", encoding="utf-8")
            result, = export_documents(source, ("docx",))
            self.assertEqual(len(Document(result).inline_shapes), 1)
            self.assertEqual(image.read_bytes(), original)

    def test_folders_include_all_pages(self):
        service = MagicMock()
        service.files.return_value.list.return_value.execute.side_effect = [
            {"files": [{"id": "a", "name": "食譜"}], "nextPageToken": "next"},
            {"files": [{"id": "b", "name": "料理"}]},
        ]
        self.assertEqual([item["id"] for item in list_folders(service)], ["a", "b"])

    def test_new_folder_retry_uses_same_id(self):
        with tempfile.TemporaryDirectory() as folder:
            service = MagicMock()
            api = service.files.return_value
            api.generateIds.return_value.execute.return_value = {"ids": ["folder-id"]}
            missing = HttpError(Response({"status": "404"}), b'{"error":"not found"}')
            api.get.return_value.execute.side_effect = [missing, {"id": "folder-id"}]
            journal = Path(folder) / "folders.json"
            for _ in range(2):
                self.assertEqual(destination_folder(service, "parent", "我的食譜", journal), "folder-id")
            api.create.assert_called_once_with(body={
                "id": "folder-id", "name": "我的食譜",
                "mimeType": "application/vnd.google-apps.folder", "parents": ["parent"],
            }, fields="id", supportsAllDrives=True)
            self.assertEqual(api.generateIds.call_count, 1)

    def test_cloud_name_and_destination_are_part_of_upload_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "食譜.pdf"
            file.write_bytes(b"pdf")
            service = MagicMock()
            api = service.files.return_value
            api.generateIds.return_value.execute.side_effect = [
                {"ids": ["file-a"]}, {"ids": ["file-b"]},
            ]
            missing = HttpError(Response({"status": "404"}), b'{"error":"not found"}')
            api.get.return_value.execute.side_effect = [missing, {"id": "file-a"}, missing]
            api.create.return_value.next_chunk.side_effect = [
                (None, {"id": "file-a"}), (None, {"id": "file-b"}),
            ]
            journal = Path(folder) / "uploads.json"
            for parent in ("folder-a", "folder-a", "folder-b"):
                upload_files([file], service, journal, parent_id=parent, file_stem="古早味肉燥")
            self.assertEqual(api.create.call_count, 2)
            metadata = [call.kwargs["body"] for call in api.create.call_args_list]
            self.assertEqual([item["name"] for item in metadata], ["古早味肉燥.pdf"] * 2)
            self.assertEqual([item["parents"] for item in metadata], [["folder-a"], ["folder-b"]])

    def test_export_contains_images_preserves_markdown_and_caches_results(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "step.jpg"
            Image.new("RGB", (240, 320), "white").save(image)
            source = root / "食譜.md"
            original = "# 測試食譜\n\n## 食材\n\n- 雞蛋：兩顆\n\n## 步驟\n\n拌勻雞蛋。\n\n![步驟](step.jpg)\n"
            source.write_text(original, encoding="utf-8")
            pdf, docx = export_documents(source, ("pdf", "docx"))
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
            with ZipFile(docx) as archive:
                self.assertIn("拌勻雞蛋", archive.read("word/document.xml").decode("utf-8"))
                self.assertTrue(any(name.startswith("word/media/") for name in archive.namelist()))
            before = [p.stat().st_mtime_ns for p in (pdf, docx)]
            self.assertEqual(export_documents(source, ("pdf", "docx")), [pdf, docx])
            self.assertEqual(before, [p.stat().st_mtime_ns for p in (pdf, docx)])
            self.assertEqual(source.read_text(encoding="utf-8"), original)
            self.assertTrue(image.is_file())
            self.assertEqual(export_documents(source, ("docx",)), [docx])
            exported_md, _, _ = export_documents(source, ("md", "pdf", "docx"))
            self.assertEqual(exported_md.read_bytes(), source.read_bytes())
            with self.assertRaises(ValueError):
                export_documents(source, ("txt",))

    def test_markdown_upload_uses_markdown_mime_type(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "食譜.md"
            source.write_text("# 食譜", encoding="utf-8")
            service = MagicMock()
            api = service.files.return_value
            api.generateIds.return_value.execute.return_value = {"ids": ["md-id"]}
            api.get.return_value.execute.side_effect = HttpError(
                Response({"status": "404"}), b'{"error":"not found"}',
            )
            api.create.return_value.next_chunk.return_value = (None, {"id": "md-id"})
            upload_files([source], service, Path(folder) / "uploads.json", file_stem="肉燥")
            self.assertEqual(api.create.call_args.kwargs["body"]["name"], "肉燥.md")
            self.assertEqual(api.create.call_args.kwargs["media_body"].mimetype(), "text/markdown")

    def test_upload_retry_reuses_ids_after_partial_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = [root / "食譜.pdf", root / "食譜.docx"]
            for path in files:
                path.write_bytes(b"test")
            service = MagicMock()
            api = service.files.return_value
            api.generateIds.return_value.execute.side_effect = [
                {"ids": ["pdf-id"]}, {"ids": ["docx-id"]},
            ]
            missing = HttpError(Response({"status": "404"}), b'{"error":"not found"}')
            api.get.return_value.execute.side_effect = [
                missing, missing, {"id": "pdf-id"}, missing,
            ]
            api.create.return_value.next_chunk.side_effect = [
                (None, {"id": "pdf-id"}), ConnectionError("connection lost"),
                (None, {"id": "docx-id"}),
            ]
            journal = root / "drive-uploads.json"
            with self.assertRaisesRegex(RuntimeError, "本機檔案"):
                upload_files(files, service, journal)
            self.assertTrue(all(path.exists() for path in files))
            self.assertEqual(len(read_json(journal)), 2)
            result = upload_files(files, service, journal)
            self.assertEqual([item["id"] for item in result], ["pdf-id", "docx-id"])
            self.assertEqual(api.generateIds.call_count, 2)
            self.assertEqual(api.create.call_count, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
