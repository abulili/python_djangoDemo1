import re
import logging
from ai_log.models import KnowledgeChunk
from ai_log.services import get_coversation_history,get_text_embedding, cosine_similarity

# 把 Agent 可以使用的能力封装成工具。给 AI 准备“可用资料”。
# 工具编排
"""
原来：查知识库 -> 拼 prompt -> AI 回答
现在：查记忆
    查知识库
    必要时查工作流
    把多个工具结果拼起来
    再让 AI 回答

就是 LangChain / Agent 的雏形。
"""

logger = logging.getLogger(__name__)

def extract_agent_keywords(text):
    text = (text or "").strip().lower()
    if not text:
        return []

    # 把文本里的英文/数字词，或者连续中文词，都提取出来
    # [a-zA-Z0-9_]+ 匹配英文、数字、下划线   [\u4e00-\u9fff]+匹配连续中文   中间的 | 是“或者”
    # text = "stream3 怎么实现 token_version 单端登录？" => ["stream3", "怎么实现", "token_version", "单端登录"]
    words = re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]{2,}", text)
    # 过滤太短的词，太短的词通常没有检索价值，容易误命中。
    # 中文里“钱”“税”“单”这种一个字也可能有意义。第一版先过滤掉是为了减少误命中，后面可以改成更细。
    keywords = []

    # 除了保留原句，还会拆出一些中文片段：
    for word in words:
        word = word.strip()
        if len(word) < 2:
            continue

        keywords.append(word)

        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            for size in [2, 3, 4]:
                for index in range(0, len(word) - size + 1):
                    keywords.append(word[index:index + size])

    return list(dict.fromkeys(keywords))

def score_text_by_keywords(query, text):
    query = (query or "").strip().lower()
    text = (text or "").strip().lower()

    if not query or not text:
        return 0

    score = 0

    for keyword in extract_agent_keywords(query):
        if keyword in text:
            # 这个关键词在文本里出现了几次, 关键词命中数量
            score += text.count(keyword)

    return score

def retrieve_knowledge_tool(user, query, top_k=3, search_type="keyword"):
    if user.is_superuser:
        chunks = KnowledgeChunk.objects.select_related("document").all()
    else:
        chunks = KnowledgeChunk.objects.select_related("document").filter(document__user=user)

    search_type = search_type or "keyword"
    query_embedding = []

    if search_type in ["vector", "hybrid"]:
        try:
            query_embedding = get_text_embedding(query)
        except Exception as e:
            logger.warning("agent 知识库查询向量生成失败: %s", e)
            query_embedding = []
    
    scored_chunks = []

    for chunk in chunks:
        keyword_score = score_text_by_keywords(query, chunk.content)
        vector_score = cosine_similarity(query_embedding, chunk.embedding)

        if search_type == "vector":
            score = vector_score
        elif search_type == "hybrid":
            score = keyword_score + vector_score * 3
        else:
            score = keyword_score

        if score <= 0:
            continue

        scored_chunks.append({
            "id": chunk.id,
            "document_id": chunk.document_id,
            "document_title": chunk.document.title,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "score": score,
            "keyword_score": keyword_score,
            "vector_score": vector_score,
            "has_embedding": bool(chunk.embedding),
        })

    scored_chunks.sort(key=lambda item: item["score"], reverse=True)

    return {
        "tool": "retrieve_knowledge",
        "description": "知识库检索工具",
        "query": query,
        "top_k": top_k,
        "search_type": search_type,
        "results": scored_chunks[:top_k],
    }

def get_conversation_memory_tool(user, conversation_id):
    messages = get_coversation_history(
        conversation_id=conversation_id,
        user=user
    )
    return {
        "tool": "conversation_memory",
        "description": "会话记忆工具",
        "conversation_id": conversation_id,
        "message_count": len(messages),
        "messages": messages[-6:],
    }

def get_workflow_summary_tool(user):
    from workflows.models import WorkflowRequest

    my_requests = WorkflowRequest.objects.filter(applicant=user)
    pending_requests = WorkflowRequest.objects.filter(current_approver=user)

    recent_requests = my_requests.order_by("-created_at")[:5]

    return {
        "tool": "workflow_summary",
        "description": "工作流摘要工具",
        "my_request_count": my_requests.count(),
        "pending_approval_count": pending_requests.count(),
        "recent_requests": [
            {
                "id": item.id,
                "title": item.title,
                "request_type": item.request_type,
                "status": item.status,
                "amount": str(item.amount) if item.amount is not None else None,
            }
            for item in recent_requests
        ],
    }

def should_use_workflow_tool(query):
    # 用户的问题是否需要调用工作流工具
    keywords = [
        "工作流",
        "审批",
        "申请",
        "付款",
        "打款",
        "流程",
        "待办",
        "通过",
        "驳回",
        "workflow",
        "approve",
        "approval",
        "payment",
        "request",
    ]
    # 只要 keywords 里面任意一个词出现在 query 里，就返回 True
    # any：只要有一个 True，整体就是 True
    return any(keyword in (query or "") for keyword in keywords)

def run_agent_tools(user, query, conversation_id=None, top_k=3, search_type="keyword"):
    tools = []

    memory_result = get_conversation_memory_tool(
        user = user,
        conversation_id=conversation_id
    )
    tools.append(memory_result)
    knowledge_result = retrieve_knowledge_tool(
        user=user,
        query=query,
        top_k=top_k,
        search_type=search_type,
    )
    tools.append(knowledge_result)

    if should_use_workflow_tool(query):
        workflow_result = get_workflow_summary_tool(user=user)
        tools.append(workflow_result)

    return {
        "tools": tools,
        "knowledge": knowledge_result,
        "memory": memory_result,
        "used_workflow": should_use_workflow_tool(query),
    }
