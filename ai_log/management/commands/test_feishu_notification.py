from django.core.management.base import BaseCommand

from ai_log.notifications.feishu import AINotificationContext, send_feishu_ai_notification

class Command(BaseCommand):
    help = "测试飞书 AI 通知"

    def handle(self, *args, **options):
        result = send_feishu_ai_notification(AINotificationContext(
            success=False,
            user_id=0,
            model_name="local-test",
            prompt="本地测试飞书 AI 通知是否可用",
            error_message="这是一条测试消息，不代表真实错误。",
            trace_id="local-test-trace-id",
            duration=0,
            total_tokens=0,
            cost=0,
        ))

        self.stdout.write(str(result))