import json
import uuid
import time

from ai_log.agent_tools import (
    get_conversation_memory_tool,
    retrieve_knowledge_tool,
    get_workflow_summary_tool,
    should_use_workflow_tool,
)
from ai_log.models import AICallLog, AiTraceStepLog
from ai_log.services import save_conversation_messages_to_db,call_jev_service

from concurrent.futures import ThreadPoolExecutor, as_completed

def route_agents(query):
    agents =  ["retriever"]

    if should_use_workflow_tool(query):
        agents.append("workflow")

    agents.append("answer")
    return agents

"""
关键词要手动维护
语义理解弱

便宜
快
稳定
可测试
"""
def route_agents_by_key(query):
    query = query or ""

    evaluation = {
        "need_memory": True,
        "need_retriever_score": 0,
        "need_workflow_score": 0,
        "need_answer": True,
        "matched_retriever_keywords": [],
        "matched_workflow_keywords": [],
    }

    retriever_keywords = [
        "知识库",
        "文档",
        "规则",
        "说明",
        "怎么实现",
        "原理",
        "RAG",
        "LangChain",
        "trace",
        "日志",
    ]

    workflow_keywords = [
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

    for keyword in retriever_keywords:
        if keyword in query:
            evaluation["need_retriever_score"] += 1
            evaluation["matched_retriever_keywords"].append(keyword)

    for keyword in workflow_keywords:
        if keyword in query:
            evaluation["need_workflow_score"] += 1
            evaluation["matched_workflow_keywords"].append(keyword)

    agents = ["memory"]

    if evaluation["need_retriever_score"] > 0:
        agents.append("retriever")

    if evaluation["need_workflow_score"] > 0:
        agents.append("workflow")

    # 如果 key 没判断出任何专业 agent，默认查知识库，避免 answer 空转
    if "retriever" not in agents and "workflow" not in agents:
        agents.append("retriever")

    agents.append("answer")

    return {
        "agents": agents,
        "evaluation": evaluation,
    }

def run_jev_router_agent(
    *,
    user,
    query,
    model_key,
    call_jev_service=None,
):
    questions = {
        "need_memory": {
            "type": "score",
            "instructions": "How much does this request need conversation memory?",
            "criteria": [
                "No memory needed",
                "Some previous conversation may help",
                "Conversation memory is required"
            ],
        },
        "need_retriever": {
            "type": "score",
            "instructions": "How much does this request need knowledge base, documents, rules, or technical reference?",
            "criteria": [
                "No knowledge retrieval needed",
                "Knowledge retrieval may help",
                "Knowledge retrieval is required"
            ],
        },
        "need_workflow": {
            "type": "score",
            "instructions": "How much does this request need workflow, approval, payment, request, or todo status data?",
            "criteria": [
                "No workflow data needed",
                "Workflow data may help",
                "Workflow data is required"
            ],
        },
    }

    result, success = call_jev_service(
        state=query,
        questions=questions,
        model=model_key,
    )

    if not success:
        return {
            "success": False,
            "selected_agents": route_agents(query),
            "evaluation": {},
            "reason": result.get("reply", "JEV 调用失败，使用规则路由"),
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
            },
            "raw": result.get("reply", ""),
        }

    data = result.get("jev_response", {})
    answers = data.get("answers", {})

    need_memory = float(answers.get("need_memory", {}).get("score", 0))
    need_retriever = float(answers.get("need_retriever", {}).get("score", 0))
    need_workflow = float(answers.get("need_workflow", {}).get("score", 0))

    agents = []

    if need_memory >= 0.5:
        agents.append("memory")
    if need_retriever >= 0.5:
        agents.append("retriever")
    if need_workflow >= 0.5:
        agents.append("workflow")

    if "retriever" not in agents and "workflow" not in agents:
        agents.append("retriever")

    # 避免空转
    agents.append("answer")

    return {
        "success": True,
        "selected_agents": agents,
        "evaluation": {
            "need_memory": need_memory,
            "need_retriever": need_retriever,
            "need_workflow": need_workflow,
        },
        "reason": "JEV score router",
        "usage": {
            "prompt_tokens": result.get("prompt_tokens", 0),
            "completion_tokens": result.get("completion_tokens", 0),
            "total_tokens": result.get("total_tokens", 0),
            "cost": result.get("cost", 0.0),
            "model": result.get("model", ""),
        },
        "raw": data,
    }

def run_supervisor_agent(
    *,
    user,
    query,
    model_key,
    call_ai_service,
):
    prompt = f"""
你是 SupervisorAgent，负责为用户问题选择需要调用的专业 Agent。

可用 Agent：
- memory：读取会话记忆
- retriever：查询知识库、文档、规则、技术资料
- workflow：查询审批、付款、申请、待办、流程状态
- answer：整合所有 Agent 结果并生成最终回答，必须选择

请只返回 JSON，不要返回 JSON 之外的内容：
{{
  "selected_agents": ["memory", "retriever", "workflow", "answer"],
  "reason": "选择这些 Agent 的原因"
}}

用户问题：
{query}
"""

    result, success = call_ai_service(
        prompt=prompt,
        model_key=model_key,
        user=user,
    )

    usage = {
        "prompt_tokens": result.get("prompt_tokens", 0),
        "completion_tokens": result.get("completion_tokens", 0),
        "total_tokens": result.get("total_tokens", 0),
        "cost": result.get("cost", 0.0),
        "duration": result.get("duration", 0.0),
        "model": model_key,
    }

    if not success:
        return {
            "success": False,
            "selected_agents": route_agents(query),
            "reason": result.get("reply", "Supervisor 调用失败，使用规则路由"),
            "usage": usage,
            "raw": result.get("reply", ""),
        }

    raw = result.get("reply", "")

    try:
        parsed = json.loads(raw)
    except Exception:
        return {
            "success": False,
            "selected_agents": route_agents(query),
            "reason": "Supervisor 返回非 JSON，使用规则路由",
            "usage": usage,
            "raw": raw,
        }

    allowed_agents = {"memory", "retriever", "workflow", "answer"}
    selected_agents = [
        item for item in parsed.get("selected_agents", [])
        if item in allowed_agents
    ]

    if "memory" not in selected_agents:
        selected_agents.insert(0, "memory")

    if "answer" not in selected_agents:
        selected_agents.append("answer")

    if "retriever" not in selected_agents and "workflow" not in selected_agents:
        selected_agents.insert(1, "retriever")

    return {
        "success": True,
        "selected_agents": selected_agents,
        "reason": parsed.get("reason", ""),
        "usage": usage,
        "raw": parsed,
    }

def run_retriever_agent(*, user, query, top_k, search_type):
    return retrieve_knowledge_tool(
        user=user,
        query=query,
        top_k=top_k,
        search_type=search_type,
    )

def run_workflow_agent(*, user):
    return get_workflow_summary_tool(user=user)

def run_answer_agent(
    *,
    user,
    query,
    conversation_id,
    model_key,
    trace_id,
    call_ai_service,
    memory_result,
    knowledge_result,
    workflow_result,
    agent_plan = None,
):
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
        else "本次问题未调用工作流 Agent"
    )

    """
    agent_plan = {
        "router_type": "supervisor",
        "selected_agents": ["memory", "retriever", "workflow", "answer"],
        "supervisor_reason": "问题涉及付款审批规则，需要知识库和工作流信息。",
    }
    要把字典转成json字符串

    ensure_ascii=False：保留中文
    indent=2：格式化缩进 2 个空格
    """
    agent_plan_context = (
        json.dumps(agent_plan, ensure_ascii=False, indent=2)
        if agent_plan
        else "暂无调度计划"
    )

    prompt = f"""
你是 AnswerAgent，负责整合多个 Agent 的结果并给出最终业务回答。

【用户问题】
{query}

【会话记忆 Agent 结果】
{memory_context or "暂无会话记忆"}

【RetrieverAgent 知识库结果】
{knowledge_context or "暂无知识库命中"}

【WorkflowAgent 工作流结果】
{workflow_context}

【Agent 调度计划】
{agent_plan_context}

回答要求：
1. 优先基于 RetrieverAgent 和 WorkflowAgent 的结果回答。
2. 不要编造 Agent 没有提供的数据。
3. 如果信息不足，请说明缺少哪些信息。
4. 回答要简洁、可用于业务判断。
"""

    result, success = call_ai_service(
        prompt=prompt,
        model_key=model_key,
        user=user,
    )

    

    return {
        "success": success,
        "prompt": prompt,
        "result": result,
        "answer": result.get("reply", ""),
    }

def run_memory_agent(*, user, conversation_id):
    return get_conversation_memory_tool(
        user=user,
        conversation_id=conversation_id,
    )

def run_multi_agent(
    *,
    user,
    query,
    conversation_id,
    top_k,
    search_type,
    model_key,
    trace_id,
    call_ai_service,
    router_type="rule",
    router_model_key=None,
):
    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    key_result = None
    jev_result = None
    supervisor_result = None

    if router_type == "key":
        key_result = route_agents_by_key(query)
        selected_agents = key_result["agents"]
    elif router_type == "jev":
        router_model_key = router_model_key or model_key
        jev_result = run_jev_router_agent(
            user=user,
            query=query,
            model_key=router_model_key,
            call_jev_service=call_jev_service,
        )
        selected_agents = jev_result["selected_agents"]
    elif router_type == "supervisor":
        router_model_key = router_model_key or model_key
        supervisor_result = run_supervisor_agent(
            user=user,
            query=query,
            model_key=router_model_key,
            call_ai_service=call_ai_service,
        )
        selected_agents = supervisor_result["selected_agents"]
    else:
        selected_agents = route_agents(query)

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="multi_agent_start",
        query=query,
        detail={
            "selected_agents": selected_agents,
            "model": model_key,
            "top_k": top_k,
            "search_type": search_type,
            "router_type": router_type,
        },
    )

    if key_result:
        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="multi_agent_key_router",
            query=query,
            detail={
                "router_type": "key",
                "selected_agents": selected_agents,
                "evaluation": key_result["evaluation"],
            },
        )

    if jev_result:
        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="multi_agent_jev_router",
            query=query,
            detail={
                "router_type": "jev",
                "selected_agents": selected_agents,
                "evaluation": jev_result["evaluation"],
                "reason": jev_result["reason"],
                "success": jev_result["success"],
                "usage": jev_result.get("usage", {}),
            },
        )

    if supervisor_result:
        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="multi_agent_supervisor",
            query=query,
            detail={
                "router_type": "supervisor",
                "selected_agents": selected_agents,
                "reason": supervisor_result.get("reason", ""),
                "success": supervisor_result.get("success", False),
                "usage": supervisor_result.get("usage", {}),
            },
        )

    parallel_result = run_parallel_context_agents(
        selected_agents=selected_agents,
        user=user,
        query=query,
        conversation_id=conversation_id,
        top_k=top_k,
        search_type=search_type,
    )
    context_results = parallel_result["results"]
    agent_timing = parallel_result["timing"]

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="multi_agent_parallel_context_done",
        query=query,
        detail={
            "parallel_agents": list(context_results.keys()),
            "parallel_agent_count": len(context_results),
            "timing": agent_timing,
        },
    )

    memory_result = context_results.get("memory") or {
        "tool": "conversation_memory",
        "message_count": 0,
        "messages": [],
    }

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="multi_agent_memory",
        query=query,
        detail={
            "message_count": memory_result.get("message_count", 0),
            "returned_count": len(memory_result.get("messages", [])),
        },
    )

    knowledge_result = context_results.get("retriever") or {
        "tool": "retrieve_knowledge",
        "results": [],
        "search_type": search_type,
        "top_k": top_k,
    }

    if "retriever" in selected_agents:
        # knowledge_result = run_retriever_agent(
        #     user=user,
        #     query=query,
        #     top_k=top_k,
        #     search_type=search_type,
        # )

        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="multi_agent_retriever",
            query=query,
            detail={
                "hit_count": len(knowledge_result.get("results", [])),
                "chunk_ids": [item["id"] for item in knowledge_result.get("results", [])],
            },
        )

    workflow_result = context_results.get("workflow") or None

    if workflow_result:
        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="multi_agent_workflow",
            query=query,
            detail={
                "my_request_count": workflow_result.get("my_request_count", 0),
                "pending_approval_count": workflow_result.get("pending_approval_count", 0),
            },
        )

    agent_plan = {
        "router_type": router_type,
        "selected_agents": selected_agents,
        "key_evaluation": key_result["evaluation"] if key_result else {},
        "jev_evaluation": jev_result["evaluation"] if jev_result else {},
        "jev_reason": jev_result["reason"] if jev_result else "",
        "supervisor_reason": supervisor_result["reason"] if supervisor_result else "",
    }

    answer_started_at = time.perf_counter()
    answer_result = run_answer_agent(
        user=user,
        query=query,
        conversation_id=conversation_id,
        model_key=model_key,
        trace_id=trace_id,
        call_ai_service=call_ai_service,
        memory_result=memory_result,
        knowledge_result=knowledge_result,
        workflow_result=workflow_result,
        agent_plan=agent_plan,
    )

    answer_duration = time.perf_counter() - answer_started_at
    agent_timing["answer"] = round(answer_duration, 4)

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="multi_agent_answer_prompt_build",
        query=query,
        detail={
            "prompt_length": len(answer_result.get("prompt", "")),
            "router_type": router_type,
            "selected_agents": selected_agents,
            "has_memory": bool(memory_result.get("messages")),
            "knowledge_hit_count": len(knowledge_result.get("results", [])),
            "has_workflow": workflow_result is not None,
        },
    )

    router_usage = {}

    if jev_result:
        router_usage = jev_result.get("usage", {})
    elif supervisor_result:
        router_usage = supervisor_result.get("usage", {})

    answer_usage = {
        "prompt_tokens": answer_result["result"].get("prompt_tokens", 0),
        "completion_tokens": answer_result["result"].get("completion_tokens", 0),
        "total_tokens": answer_result["result"].get("total_tokens", 0),
        "cost": answer_result["result"].get("cost", 0.0),
    }

    usage_summary = {
        "router_tokens": router_usage.get("total_tokens", 0),
        "answer_tokens": answer_usage.get("total_tokens", 0),
        "total_tokens": router_usage.get("total_tokens", 0) + answer_usage.get("total_tokens", 0),
        "router_cost": router_usage.get("cost", 0.0),
        "answer_cost": answer_usage.get("cost", 0.0),
        "total_cost": router_usage.get("cost", 0.0) + answer_usage.get("cost", 0.0),
    }

    if not answer_result["success"]:
        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="multi_agent_failed",
            query=query,
            success=False,
            error_message=answer_result["answer"],
            detail={
                "selected_agents": selected_agents,
            },
        )

        return {
            "success": False,
            "error": answer_result["answer"],
            "conversation_id": conversation_id,
            "agents": selected_agents,
            "references": knowledge_result.get("results", []),
        }

    answer = answer_result["answer"]

    AICallLog.objects.create(
        conversation_id=conversation_id,
        prompt=query,
        response=answer,
        duration=answer_result["result"].get("duration", 0.0),
        success=True,
        user=user,
        model_name=model_key,
        prompt_tokens=answer_result["result"].get("prompt_tokens", 0),
        completion_tokens=answer_result["result"].get("completion_tokens", 0),
        total_tokens=answer_result["result"].get("total_tokens", 0),
        cost=answer_result["result"].get("cost", 0.0),
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
        step="multi_agent_done",
        query=query,
        detail={
            "selected_agents": selected_agents,
            "answer_length": len(answer),
            "knowledge_hit_count": len(knowledge_result.get("results", [])),
            "used_workflow_agent": workflow_result is not None,
            "router_type": router_type,
            "usage_summary": usage_summary,
        },
    )

    return {
        "success": True,
        "query": query,
        "answer": answer,
        "conversation_id": conversation_id,
        "search_type": search_type,
        "agents": selected_agents,
        "references": knowledge_result.get("results", []),
        "framework": "multi-agent-router",
        "router_type": router_type,
        "key_evaluation": key_result["evaluation"] if key_result else {},
        "jev_evaluation": jev_result["evaluation"] if jev_result else {},
        "jev_reason": jev_result["reason"] if jev_result else "",
        "jev_usage": jev_result.get("usage", {}) if jev_result else {},
        "supervisor_reason": supervisor_result["reason"] if supervisor_result else "",
        "supervisor_usage": supervisor_result.get("usage", {}) if supervisor_result else {},
        "usage_summary": usage_summary,
        "agent_timing": agent_timing,
    }    

def run_parallel_context_agents(
    *,
    selected_agents,
    user,
    query,
    conversation_id,
    top_k,
    search_type,
):

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_agent = {}

        started_at = time.perf_counter()
        future_started_at = {}
        timing = {}

        # 这句不会直接返回结果，而是返回一个 Future = 任务收据 / 任务句柄
        # 我把任务交给线程池了，这是取结果用的小票
        memory_future = executor.submit(
            run_memory_agent,
            user=user,
            conversation_id=conversation_id,
        )
        future_to_agent[memory_future] = "memory"
        future_started_at[memory_future] = time.perf_counter()

        if "retriever" in selected_agents:
            retriever_future = executor.submit(
                run_retriever_agent,
                user=user,
                query=query,
                top_k=top_k,
                search_type=search_type,
            )
            future_to_agent[retriever_future] = "retriever"
            future_started_at[retriever_future] = time.perf_counter()

        if "workflow" in selected_agents:
            workflow_future = executor.submit(
                run_workflow_agent,
                user=user,
            )
            future_to_agent[workflow_future] = "workflow"
            future_started_at[workflow_future] = time.perf_counter()

        results = {}
        """
        tasks = {
            "memory": Future(...),
            "retriever": Future(...),
            "workflow": Future(...),
        }

        for future in as_completed(tasks.values()): 谁先执行完，就先把谁交出来
        as_completed(...) 会监听这些 Future，按完成顺序返回。
        memory      0.1s 完成
        workflow    0.3s 完成
        retriever   1.2s 完成

        memory_future
        workflow_future
        retriever_future
        """
        # tasks.values() 里一开始放的就是 Future 对象，也就是“已经提交出去、未来会完成的任务句柄
        """
        外层 for：每完成一个 future，就处理一次
        内层 next 里的 for：为了找这个 future 对应哪个 agent，再遍历 tasks
        """
        
        for future in as_completed(future_to_agent):
            # 反查这个完成的 future 对应哪个 agent 名字
            """
            next(...) 的作用是：从一个可迭代对象里取第一个结果。
            
            等价于
            for name, task_future in tasks.items():
                if task_future == future:
                    agent_name = name
                    break

            name for name, task_future in tasks.items() 会生成符合条件的 name

            name="memory", task_future=memory_future
            memory_future == retriever_future ? 否

            name="retriever", task_future=retriever_future
            retriever_future == retriever_future ? 是
            生成 "retriever"

            next(...) 拿到第一个生成的值："retriever"
            """
            # agent_name = next(
            #     name for name, task_future in tasks.items()
            #     if task_future == future
            # )
            agent_name = future_to_agent[future]
            # future.result() 取这个任务的返回值; 如果任务还没完成，就等它完成; 如果任务抛异常，这里会重新抛出来
            results[agent_name] = future.result()
            timing[agent_name] = round(time.perf_counter() - future_started_at[future], 4)

    timing["parallel_total"] = round(time.perf_counter() - started_at, 4)

    return {
        "results": results,
        "timing": timing,
    }
    


