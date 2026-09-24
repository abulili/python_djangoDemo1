import json
import uuid

from ai_log.agent_tools import (
    get_conversation_memory_tool,
    retrieve_knowledge_tool,
    get_workflow_summary_tool,
    should_use_workflow_tool,
)
from ai_log.models import AICallLog, AiTraceStepLog
from ai_log.services import save_conversation_messages_to_db, get_prompt

try:
    from langchain_core.tools import Tool as LangChainTool
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.runnables import RunnableLambda
except ImportError:
    LangChainTool = None
    ChatPromptTemplate = None
    RunnableLambda = None

class LangChainStyleTool:
    """
    轻量 LangChain-style Tool。

    作用：
    1. 给每个工具统一 name / description / run。
    2. 方便以后替换成 langchain.tools.Tool。
    3. 让项目里能清楚体现“工具编排”。
    """

    def __init__(self, name, description, func):
        self.name = name
        self.description = description
        self.func = func

    def run(self, **kwargs):
        return self.func(**kwargs)

def build_langchain_style_tools():
    return [
        LangChainStyleTool(
            name="conversation_memory",
            description="读取当前 conversation_id 下的最近会话记忆",
            func=lambda user, query, conversation_id, top_k, search_type: get_conversation_memory_tool(user=user, conversation_id=conversation_id)
        ),
        LangChainStyleTool(
            name="knowledge_retriever",
            description="从知识库中按 keyword/vector/hybrid 检索相关片段",
            func=lambda user, query, conversation_id, top_k, search_type: retrieve_knowledge_tool(
                user=user,
                query=query,
                top_k=top_k,
                search_type=search_type,
            ),
        ),
        LangChainStyleTool(
            name="workflow_summary",
            description="读取当前用户的工作流申请、待审批和最近申请摘要",
            func=lambda user, query, conversation_id, top_k, search_type: get_workflow_summary_tool(
                user=user,
            ),
        ),
    ]

def build_optional_langchain_tools(style_tools):
    """
    如果安装了 langchain_core，就把当前轻量 Tool 转成 LangChain Tool。
    如果没安装，就返回空列表，不影响主流程。
    """
    if LangChainTool is None:
        return []

    langchain_tools = []

    for style_tool in style_tools:
        langchain_tools.append(
            LangChainTool.from_function(
                name=style_tool.name,
                description=style_tool.description,
                func=lambda input_text, tool=style_tool: tool.run(
                    user=input_text["user"],
                    query=input_text["query"],
                    conversation_id=input_text.get("conversation_id"),
                    top_k=input_text.get("top_k", 3),
                    search_type=input_text.get("search_type", "hybrid"),
                ),
            )
        )

    return langchain_tools

def run_langchain_style_agent(
    *,
    user,
    query,
    conversation_id,
    top_k,
    search_type,
    model_key,
    trace_id,
    call_ai_service,
    business_template_name=None,
    business_template_vars=None,
):
    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    tools = build_langchain_style_tools()
    langchain_tools = build_optional_langchain_tools(tools)
    # 是否ChatPromptTemplate和RunnableLambda
    using_langchain_core = ChatPromptTemplate is not None and RunnableLambda is not None
    
    if not using_langchain_core:
        return {
            "success": False,
            "error": "当前环境未安装 langchain-core，无法执行 LangChain RunnableSequence",
            "conversation_id": conversation_id,
            "tools": [],
            "references": [],
            "using_langchain_core": False,
        }

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="langchain_agent_start",
        query=query,
        detail={
            "framework": "langchain-core-runnable-sequence",
            "using_langchain_core": using_langchain_core,
            "top_k": top_k,
            "search_type": search_type,
            "model": model_key,
        },
    )

    
    tool_outputs = []
    memory_result = None
    knowledge_result = None
    workflow_result = None

    for tool in tools:
        if tool.name == "workflow_summary" and not should_use_workflow_tool(query):
            continue

        output = tool.run(
            user = user,
            query = query,
            conversation_id = conversation_id,
            top_k = top_k,
            search_type = search_type,
        )

        tool_outputs.append({
            "tool": tool.name,
            "description": tool.description,
            "output": output,
        })

        if tool.name == "conversation_memory":
            memory_result = output
            AiTraceStepLog.objects.create(
                user=user,
                trace_id=trace_id,
                conversation_id=conversation_id,
                step="langchain_tool_memory",
                query=query,
                detail={
                    "message_count": output["message_count"],
                    "returned_count": len(output["messages"]),
                },
            )

        if tool.name == "knowledge_retriever":
            knowledge_result = output
            AiTraceStepLog.objects.create(
                user=user,
                trace_id=trace_id,
                conversation_id=conversation_id,
                step="langchain_tool_retriever",
                query=query,
                detail={
                    "search_type": output["search_type"],
                    "top_k": output["top_k"],
                    "hit_count": len(output["results"]),
                    "chunk_ids": [item["id"] for item in output["results"]],
                },
            )

        if tool.name == "workflow_summary":
            workflow_result = output
            AiTraceStepLog.objects.create(
                user=user,
                trace_id=trace_id,
                conversation_id=conversation_id,
                step="langchain_tool_workflow",
                query=query,
                detail={
                    "my_request_count": output["my_request_count"],
                    "pending_approval_count": output["pending_approval_count"],
                    "recent_request_count": len(output["recent_requests"]),
                },
            )

    memory_result = memory_result or {
        "tool": "conversation_memory",
        "message_count": 0,
        "messages": [],
    }
    knowledge_result = knowledge_result or {
        "tool": "retrieve_knowledge",
        "results": [],
        "search_type": search_type,
        "top_k": top_k,
    }

    memory_context = "\n".join([
        f"{item.get('role')}: {item.get('content')}"
        for item in memory_result.get("messages", [])
    ])

    knowledge_context = "\n\n".join([
        f"资料{index + 1}：{item['content']}"
        for index, item in enumerate(knowledge_result.get("results", []))
    ])

    workflow_context = (
        json.dumps(workflow_result, ensure_ascii=False)
        if workflow_result
        else "本次问题未调用工作流工具"
    )

    tool_plan = [
        {
            "name": item["tool"],
            "description": item["description"],
        }
        for item in tool_outputs
    ]

    """
    没传 template_name：正常继续
    传了 template_name 且存在：使用模板
    传了 template_name 但不存在：返回 400
    模板变量缺失：返回 400
    """

    business_prompt = query
    business_template_used = False

    if business_template_name:
        try:
            rendered_prompt = get_prompt(
                business_template_name,
                business_template_vars or {},
            )
        except ValueError as exc:
            return {
                "success": False,
                "error": str(exc),
                "code": 400,
                "conversation_id": conversation_id,
                "tools": tool_outputs,
                "references": knowledge_result.get("results", []),
                "using_langchain_core": using_langchain_core,
                "framework": "langchain-core-runnable-sequence",
            }   
        # 传了template_name，但数据库里找不到
        if not rendered_prompt:
            return {
                "success": False,
                "error": f"业务 Prompt 模板不存在或未启用: {business_template_name}",
                "code": 400,
                "conversation_id": conversation_id,
                "tools": tool_outputs,
                "references": knowledge_result.get("results", []),
                "using_langchain_core": using_langchain_core,
                "framework": "langchain-core-runnable-sequence",
            }
        business_prompt = rendered_prompt
        business_template_used = True

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="langchain_business_prompt",
        query=query,
        detail={
            "template_name": business_template_name or "",
            "template_used": business_template_used,
            "business_prompt_length": len(business_prompt or ""),
        },
    )

    prompt_template = ChatPromptTemplate.from_messages([
    (
        "system",
        "你是一个支持工具编排的业务 AI 助手。你正在使用 LangChain RunnableSequence 流程回答问题。"
        "回答必须优先基于知识库、会话记忆、工作流工具结果，不要编造工具结果里不存在的数据。"
    ),
    (
        "human",
        """
【工具计划】
{tool_plan}

【会话记忆】
{memory_context}

【知识库检索结果】
{knowledge_context}

【工作流工具结果】
{workflow_context}

【用户问题】
{query}

【业务 Prompt 模板结果】
{business_prompt}

回答要求：
1. 优先基于知识库和工具结果回答。
2. 如果使用了工作流工具，要结合申请数量、待审批数量、最近申请说明。
3. 如果资料不足，请明确说明缺少什么。
4. 回答要简洁、可用于业务判断。
"""
    ),
])

    def call_existing_ai(prompt_value):
        prompt_text  = prompt_value.to_string()

        result, success = call_ai_service(
            prompt=prompt_text,
            model_key=model_key,
            user=user,
        )

        return {
            "prompt": prompt_text,
            "result": result,
            "success": success,
        }

    """
    先用 prompt_template 把变量拼成 LangChain 的 PromptValue
    再把这个 PromptValue 交给 call_existing_ai 去调用你现有的 AI 服务

    | 是 LangChain Runnable 的管道操作符，类似前端里的“上一段输出传给下一段输入”。

    等价于：
    prompt_value = prompt_template.invoke({
        "query": query,
        "memory_context": memory_context,
        ...
    })

    chain_output = call_existing_ai(prompt_value)
    """
    chain = prompt_template | RunnableLambda(call_existing_ai)

    chain_output = chain.invoke({
        "tool_plan": json.dumps(tool_plan, ensure_ascii=False),
        "memory_context": memory_context or "暂无会话记忆",
        "knowledge_context": knowledge_context or "暂无知识库命中",
        "workflow_context": workflow_context,
        "query": query,
        "business_prompt": business_prompt,
    })

    prompt = chain_output["prompt"]
    result = chain_output["result"]
    success = chain_output["success"]


    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="langchain_prompt_build",
        query=query,
        detail={
            "prompt_length": len(prompt),
            "tool_count": len(tool_outputs),
            "knowledge_hit_count": len(knowledge_result.get("results", [])),
            "memory_message_count": memory_result.get("message_count", 0),
            "used_workflow": workflow_result is not None,
            "chain_type": "ChatPromptTemplate|RunnableLambda",
            "framework": "langchain-core-runnable-sequence",
            "business_template_name": business_template_name or "",
            "business_template_used": business_template_used,
        },
    )
    # 由chain调用了
    # result, success = call_ai_service(
    #     prompt=prompt,
    #     model_key=model_key,
    #     user=user,
    # )

    if not success:
        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="langchain_agent_failed",
            query=query,
            success=False,
            error_message=result.get("reply", "AI 调用失败"),
            detail={
                "model": model_key,
                "framework": "langchain-core-runnable-sequence",
            },
        )

        return {
            "success": False,
            "error": result.get("reply", "AI 调用失败"),
            "conversation_id": conversation_id,
            "tools": tool_outputs,
            "references": knowledge_result.get("results", []),
            "using_langchain_core": using_langchain_core,
        }

    answer = result.get("reply", "")

    AICallLog.objects.create(
        conversation_id=conversation_id,
        prompt=query,
        response=answer,
        duration=result.get("duration", 0.0),
        success=True,
        user=user,
        model_name=model_key,
        prompt_tokens=result.get("prompt_tokens", 0),
        completion_tokens=result.get("completion_tokens", 0),
        total_tokens=result.get("total_tokens", 0),
        cost=result.get("cost", 0.0),
        trace_id=trace_id,
    )

    save_conversation_messages_to_db(
        conversation_id=conversation_id,
        user=user,
        user_content=query,
        assistant_content=answer,
    )

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="langchain_agent_done",
        query=query,
        detail={
            "answer_length": len(answer),
            "tool_count": len(tool_outputs),
            "knowledge_hit_count": len(knowledge_result.get("results", [])),
            "total_tokens": result.get("total_tokens", 0),
            "cost": result.get("cost", 0.0),
            "framework": "langchain-core-runnable-sequence",
        },
    )

    return {
        "success": True,
        "query": query,
        "answer": answer,
        "conversation_id": conversation_id,
        "search_type": search_type,
        "tools": tool_outputs,
        "references": knowledge_result.get("results", []),
        "framework": "langchain-core-runnable-sequence",
        "using_langchain_core": True,
    }


