"""共享的 FastAPI 依赖（shared FastAPI dependencies）。

为什么存在这个文件
--------------------
重构前，五个路由模块（upload / transcribe / generate / export / audio）各自
复制粘贴了同一段"按 task_id 查任务、查不到就 404"的代码：

    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_TEXT)  # 各处文案一字不差

复制粘贴的代价：
  * 想改 404 文案/状态码时要改 N 处，漏一处就行为不一致；
  * 新写的路由容易忘记空值检查，直接对 None 调属性导致 500。

于是把"任务不存在"这一行为收敛到本文件：ensure_task_or_404 是全仓库唯一
抛出 404 "Task not found" 的位置；get_task_or_404 是它的依赖包装（按路径
参数查任务）；TaskDep 是注入用的类型别名。

注意（Metis F3）
----------------
transcribe.py 的 SSE 流式接口内部还有一个 `{"error": "Task not found"}`，
那是发给浏览器的流式事件负载（wire content），不是 HTTPException，语义
完全不同，必须保持原样——不要试图用本依赖替换它。

注意（测试补丁的落点）
----------------------
tests/test_routers_transcribe_generate.py 会把假的 get_task 补丁打进
transcribe 模块自己的命名空间（router 按名字导入 get_task，补丁只对
该命名空间内的调用生效）。因此 transcribe.py 在本地包了一层晚绑定适配
（_task_or_404）：先用自己的 get_task 查询，再交给 ensure_task_or_404
做 404 判定。其余路由没有这类补丁，直接注入本文件的 TaskDep 即可。

用法
----
路径参数型路由（task_id 在 URL 里）：

    @router.get("/task/{task_id}")
    async def get_task_info(task: TaskDep):   # 注入后即为 TaskInfo 或直接 404
        return task

请求体型路由（task_id 在请求体里，如 POST /generate）没有路径参数可注入，
直接调用依赖函数即可：

    task = get_task_or_404(req.task_id)
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Path

from backend.app.models.schemas import TaskInfo
from backend.app.services.store import get_task

# 404 文案用常量组织：既保证全仓库只有一处定义，
# 也方便用 grep 验证旧的复制粘贴写法已清零。
_TASK_NOT_FOUND = "Task not found"


def ensure_task_or_404(task: TaskInfo | None) -> TaskInfo:
    """任务不存在则抛 HTTPException(404)；否则原样返回。

    全仓库唯一抛出 404 "Task not found" 的位置——文案与状态码只在这里定义。
    """
    if task is None:
        raise HTTPException(status_code=404, detail=_TASK_NOT_FOUND)
    return task


def get_task_or_404(task_id: str = Path(..., description="任务 ID")) -> TaskInfo:
    """按路径参数 task_id 查任务；不存在则抛 HTTPException(404)。

    FastAPI 依赖函数：注入到路由签名（经 TaskDep 别名）后，框架会自己从
    路径的 {task_id} 解析参数。返回 TaskInfo 而不是只做校验，是为了让
    处理器拿到任务对象后能继续做状态检查（如"任务正在转录中"），
    不必再查一次 store。
    """
    return ensure_task_or_404(get_task(task_id))


# 注入用类型别名：`task: TaskDep` 等价于注入 get_task_or_404 的返回值。
TaskDep = Annotated[TaskInfo, Depends(get_task_or_404)]
