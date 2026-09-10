import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# 同一个 request_id python scripts\light_load_test.py --username 你的用户名 --password 你的密码 --total 20 --workers 5 --same-request-id
# 再跑“不同 request_id”模式： python scripts\light_load_test.py --username 你的用户名 --password 你的密码 --total 30 --workers 10

def login(base_url, username, password):
    response = requests.post(
        f"{base_url}/api/token/",
        json={
            "username": username,
            "password": password,
        },
        timeout=10,
    )
    # 如果 HTTP 状态码是错误，比如 400、401、403、500，就直接抛异常
    response.raise_for_status()
    return response.json()["access"]


def post_task(base_url, token, index, same_request_id=False):
    request_id = "load-test-same-request" if same_request_id else f"load-test-request-{index}"
    # 测耗时的高精度计时器
    started_at = time.perf_counter()
    response = requests.post(
        f"{base_url}/api/logs/call_company_ai4/",
        headers={
            "Authorization": f"Bearer {token}",
        },
        json={
            "prompt": f"轻量压测请求 {index}",
            "model": "deepseek",
            "conversation_id": "load-test-conversation",
            "request_id": request_id,
        },
        timeout=20,
    )
    duration_ms = (time.perf_counter() - started_at) * 1000

    task_id = None
    try:
        data = response.json()
        task_id = data.get("data", {}).get("task_id")
    except ValueError:
        data = None

    return {
        "status_code": response.status_code,
        "duration_ms": duration_ms,
        "task_id": task_id,
        "body": data,
    }

def poll_task(base_url, token, task_id):
    started_at = time.perf_counter()
    response = requests.get(
        f"{base_url}/api/logs/task/{task_id}/",
        headers={
            "Authorization": f"Bearer {token}",
        },
        timeout=20,
    )
    duration_ms = (time.perf_counter() - started_at) * 1000

    try:
        data = response.json()
    except ValueError:
        data = None

    return {
        "status_code": response.status_code,
        "duration_ms": duration_ms,
        "task_id": task_id,
        "body": data,
    }

def summarize(results):
    # 汇总结果
    status_counts = {}
    durations = []

    for item in results:
        status_counts[item["status_code"]] = status_counts.get(item["status_code"], 0) + 1
        durations.append(item["duration_ms"])

    durations_sorted = sorted(durations)
    """
    p95 叫第 95 百分位耗时。
    如果发了 100 个请求，把耗时从小到大排序：
    第 95 个请求的耗时，就是 p95，比平均值更适合看“多数用户的慢请求体验”。95% 请求都能在这个时间内完成
    """
    p95_index = int(len(durations_sorted) * 0.95) - 1
    p95_index = max(0, min(p95_index, len(durations_sorted) - 1))

    task_ids = [item["task_id"] for item in results if item["task_id"]]

    print("status_counts:", status_counts) # 不同状态码各有多少个
    print("avg_ms:", round(statistics.mean(durations), 2))
    print("p95_ms:", round(durations_sorted[p95_index], 2)) # 95% 请求以内的耗时
    print("unique_task_ids:", len(set(task_ids))) # 一共创建/返回了多少个不同 task_id
    print("task_id_samples:", list(dict.fromkeys(task_ids))[:5]) # 展示几个 task_id 样例


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--total", type=int, default=20)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--same-request-id", action="store_true")

    parser.add_argument("--mode", choices=["submit-task", "poll-task"], default="submit-task")
    parser.add_argument("--task-id")

    args = parser.parse_args()

    token = login(args.base_url, args.username, args.password)

    if args.mode == "poll-task" and not args.task_id:
        raise ValueError("--mode poll-task 需要提供 --task-id")

    results = []
    # 线程池  意思是最多同时跑几个请求
    # 压力测试两个接口
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        if args.mode == "poll-task":
            futures = [
                executor.submit(poll_task, args.base_url, token, args.task_id)
                for _ in range(args.total)
            ]
        else:
            futures = [
                executor.submit(post_task, args.base_url, token, index, args.same_request_id)
                for index in range(args.total)
            ]

        for future in as_completed(futures):
            results.append(future.result())

    summarize(results)


if __name__ == "__main__":
    main()