from django.core.management.base import BaseCommand

from ai_log.models import KnowledgeChunk
from ai_log.services import get_text_embedding

# 管理命令，把旧的 KnowledgeChunk 批量生成 embedding
# python manage.py rebuild_knowledge_embeddings 默认只补空的旧数据
# python manage.py rebuild_knowledge_embeddings --limit 5 小批量尝试
# python manage.py rebuild_knowledge_embeddings --force 重新生成

# 换了embedding模型 / 改了切片内容 / 之前生成的embedding逻辑有bug
class Command(BaseCommand):
    help = "为知识库切片批量生成 embedding"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="最多处理多少条，0 表示不限制",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="是否强制重新生成已有 embedding 的切片",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        force = options["force"]

        chunks = KnowledgeChunk.objects.select_related("document").order_by("id")

        processed_count = 0
        skipped_count = 0
        failed_count = 0

        for chunk in chunks.iterator():
            if limit and processed_count >= limit:
                break

            if chunk.embedding and not force:
                skipped_count += 1
                continue

            try:
                embedding = get_text_embedding(chunk.content)

                if not embedding:
                    skipped_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"跳过 chunk_id={chunk.id}，未生成 embedding"
                        )
                    )
                    continue

                chunk.embedding = embedding
                chunk.save(update_fields=["embedding"])

                processed_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"已生成 embedding：chunk_id={chunk.id}，document={chunk.document.title}"
                    )
                )

            except Exception as exc:
                failed_count += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"生成失败：chunk_id={chunk.id}，error={exc}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"完成：processed={processed_count}, skipped={skipped_count}, failed={failed_count}"
            )
        )