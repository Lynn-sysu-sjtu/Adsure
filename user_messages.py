"""Centralized text that may be shown to ordinary users."""

ACTION_ACCEPTED = "已收到，完成后会通知你"
ACTION_IN_PROGRESS = "正在处理中，请稍候"
TRANSFERRED_TO_LEGAL = "已转交法务"
STALE_CARD = "这张卡片已失效，请打开最新消息"
ACTION_RETRY = "这次没有处理完成，请稍后再试"
WORKBENCH_UNAVAILABLE = "暂时未能加载，请稍后刷新"
REVIEW_SUBMIT_UNAVAILABLE = "暂时未能提交，请稍后再试"

FINAL_FAILURE_TITLE = "暂时没有处理完成"
FINAL_FAILURE_BODY = "请稍后再试一次"
FINAL_FAILURE_BUTTON = "重新尝试"


def required_field(field_name: str) -> str:
    return f"请补充{field_name}"
