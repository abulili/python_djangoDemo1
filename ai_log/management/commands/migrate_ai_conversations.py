from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Max, Min
from ai_log.models import AICallLog, PromptTemplate, Conversation, ConversationMessage

class Command(BaseCommand):
    # python manage.py migrate_ai_conversations
    help = "将旧的 AICallLog 记录迁移到 Conversation 和 ConversationMessage 表中"

    # *args 接收普通位置参数。 python manage.py migrate_ai_conversations aaa bbb
    # **options 接收命令选项。python manage.py migrate_ai_conversations --dry-run
    def handle(self, *args, **options):
        logs = (
            AICallLog.objects
            .exclude(conversation_id__isnull=True) # 只迁移有 conversation_id 的日志
            .exclude(conversation_id='') # 按 conversation_id 分组,每个旧会话只创建一个 Conversation
            .exclude(user__isnull=True)
            .order_by('conversation_id', 'call_time')
        )

        conversation_ids = (
            logs
            .values("conversation_id")
            .annotate( # 给每组算统计值
                first_time=Min("call_time"),
                last_time=Max("call_time"),
                total=Count("id"),
            )
            .order_by("conversation_id")
        )

        created_conversations = 0
        created_messages = 0
        skipped_conversations = 0

        with transaction.atomic():
            for item in conversation_ids:
                conversation_id = item["conversation_id"]

                first_log = logs.filter(conversation_id=conversation_id).first()
                if not first_log:
                    continue

                conversation, created = Conversation.objects.get_or_create(
                    conversation_id=conversation_id,
                    defaults={
                        "user": first_log.user,
                        "title": first_log.prompt[:30] if first_log.prompt else "",
                    }
                )

                if not created: # 如果这个会话已经存在就跳过，避免重复迁移
                    skipped_conversations += 1
                    continue

                created_conversations += 1

                current_logs = logs.filter(conversation_id=conversation_id, user=first_log.user).order_by('call_time')

                # 旧日志拆成消息
                for log in current_logs:
                    ConversationMessage.objects.create(
                        conversation=conversation,
                        role="user",
                        content=log.prompt or "",
                    )
                    created_messages += 1

                    if log.response:
                        ConversationMessage.objects.create(
                            conversation=conversation,
                            role="assistant",
                            content=log.response,
                        )
                        created_messages += 1
        
        self.stdout.write(self.style.SUCCESS(f"成功迁移 {created_conversations} 个对话，{created_messages} 条消息，跳过 {skipped_conversations} 个对话"))
            


