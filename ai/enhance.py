import os
import json
import sys
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict
from queue import Queue
from threading import Lock
# INSERT_YOUR_CODE
import requests

import dotenv
import argparse
from tqdm import tqdm

import langchain_core.exceptions
from langchain_openai import ChatOpenAI
from openai import OpenAI
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from structure import Structure

if os.path.exists('.env'):
    dotenv.load_dotenv()
with open("template.txt", "r", encoding="utf-8") as template_file:
    template = template_file.read()
with open("system.txt", "r", encoding="utf-8") as system_file:
    system = system_file.read()

AI_FIELDS = ["tldr", "motivation", "method", "result", "conclusion", "detailed_summary"]

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, required=True, help="jsonline data file")
    parser.add_argument("--max_workers", type=int, default=1, help="Maximum number of parallel workers")
    return parser.parse_args()

def default_ai_fields():
    return {
        "tldr": "摘要生成失败",
        "motivation": "动机分析不可用",
        "method": "方法提取失败",
        "result": "结果分析不可用",
        "conclusion": "结论提取失败",
        "detailed_summary": "详细总结生成失败"
    }

def parse_ai_json_response(content: str) -> Dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))

    defaults = default_ai_fields()
    return {field: str(data.get(field) or defaults[field]) for field in AI_FIELDS}

class TrapiEnhancer:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.timeout = int(os.environ.get("TRAPI_TIMEOUT") or "600")
        apipath = os.environ.get("TRAPI_APIPATH", "gcr/shared")
        endpoint = os.environ.get("TRAPI_ENDPOINT", f"https://trapi.research.microsoft.com/{apipath}/openai/v1")
        api_key = os.environ.get("TRAPI_API_KEY") or os.environ.get("AZURE_OPENAI_API_KEY")

        if not api_key and os.environ.get("TRAPI_USE_OPENAI_API_KEY", "false").lower() in {"1", "true", "yes"}:
            api_key = os.environ.get("OPENAI_API_KEY")

        if not api_key:
            from azure.identity import (
                AzureCliCredential,
                ChainedTokenCredential,
                ManagedIdentityCredential,
                get_bearer_token_provider,
            )

            scope = os.environ.get("TRAPI_SCOPE", "api://trapi/.default")
            credential = get_bearer_token_provider(
                ChainedTokenCredential(
                    AzureCliCredential(),
                    ManagedIdentityCredential(),
                ),
                scope,
            )
            api_key = credential()

        self.client = OpenAI(base_url=endpoint, api_key=api_key)

    def __call__(self, content: str, language: str) -> Dict:
        user_prompt = template.format(content=content)
        json_instruction = (
            "请只输出一个合法 JSON 对象，不要 Markdown，不要额外解释。"
            "JSON 必须包含 tldr、motivation、method、result、conclusion、detailed_summary 六个键。"
            "其中 detailed_summary 请尽量详细、分点回答：1. 这篇文章解决了什么问题；2. 有哪些相关工作；"
            "3. 采用了什么研究方法；4. 做了哪些实验、结果如何；5. 结论是什么；最后再整体总结这篇文章的核心内容。"
            f"所有字段必须使用{language}，如果 language 是 Chinese，请使用简体中文。"
        )
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": f"{system}\n{json_instruction}"},
                {"role": "user", "content": user_prompt},
            ],
            timeout=self.timeout,
        )
        return parse_ai_json_response(response.choices[0].message.content or "")

class LangChainEnhancer:
    def __init__(self, model_name: str):
        llm = ChatOpenAI(
            model=model_name,
            model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}}
        ).with_structured_output(Structure, method="function_calling")
        prompt_template = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(system),
            HumanMessagePromptTemplate.from_template(template=template)
        ])
        self.chain = prompt_template | llm

    def __call__(self, content: str, language: str) -> Dict:
        response: Structure = self.chain.invoke({
            "language": language,
            "content": content,
        })
        return response.model_dump()

def build_enhancer(provider: str, model_name: str):
    if provider == "openai":
        return LangChainEnhancer(model_name)
    if provider != "trapi":
        raise ValueError(f"Unsupported AI_PROVIDER: {provider}")
    return TrapiEnhancer(model_name)

def process_single_item(enhancer, item: Dict, language: str) -> Dict:
    def is_sensitive(content: str) -> bool:
        """
        调用 spam.dw-dengwei.workers.dev 接口检测内容是否包含敏感词。
        返回 True 表示触发敏感词，False 表示未触发。
        """
        if os.environ.get("ENABLE_SENSITIVE_CHECK", "true").lower() in {"0", "false", "no"}:
            return False

        try:
            resp = requests.post(
                "https://spam.dw-dengwei.workers.dev",
                json={"text": content},
                timeout=5
            )
            if resp.status_code == 200:
                result = resp.json()
                # 约定接口返回 {"sensitive": true/false, ...}
                return result.get("sensitive", True)
            else:
                # 如果接口异常，默认不触发敏感词
                print(f"Sensitive check failed with status {resp.status_code}", file=sys.stderr)
                return True
        except Exception as e:
            print(f"Sensitive check error: {e}", file=sys.stderr)
            return True

    def check_github_code(content: str) -> Dict:
        """提取并验证 GitHub 链接"""
        code_info = {}

        # 1. 优先匹配 github.com/owner/repo 格式
        github_pattern = r"https?://github\.com/([a-zA-Z0-9-_]+)/([a-zA-Z0-9-_\.]+)"
        match = re.search(github_pattern, content)
        
        if match:
            owner, repo = match.groups()
            # 清理 repo 名称，去掉可能的 .git 后缀或末尾的标点
            repo = repo.rstrip(".git").rstrip(".,)")
            
            full_url = f"https://github.com/{owner}/{repo}"
            code_info["code_url"] = full_url
            
            # 尝试调用 GitHub API 获取信息
            github_token = os.environ.get("TOKEN_GITHUB")
            headers = {"Accept": "application/vnd.github.v3+json"}
            if github_token:
                headers["Authorization"] = f"token {github_token}"
            
            try:
                api_url = f"https://api.github.com/repos/{owner}/{repo}"
                resp = requests.get(api_url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    code_info["code_stars"] = data.get("stargazers_count", 0)
                    code_info["code_last_update"] = data.get("pushed_at", "")[:10]
            except Exception:
                # API 调用失败不影响主流程
                pass
            return code_info

        # 2. 如果没有 github.com，尝试匹配 github.io
        github_io_pattern = r"https?://[a-zA-Z0-9-_]+\.github\.io(?:/[a-zA-Z0-9-_\.]+)*"
        match_io = re.search(github_io_pattern, content)
        
        if match_io:
            url = match_io.group(0)
            # 清理末尾标点
            url = url.rstrip(".,)")
            code_info["code_url"] = url
            # github.io 不进行 star 和 update 判断
                
        return code_info

    # 检查 summary 字段
    if is_sensitive(item.get("summary", "")):
        return None

    # 检测代码可用性
    code_info = check_github_code(item.get("summary", ""))
    if code_info:
        item.update(code_info)

    """处理单个数据项"""
    defaults = default_ai_fields()
    
    try:
        item['AI'] = {**defaults, **enhancer(item['summary'], language)}
    except langchain_core.exceptions.OutputParserException as e:
        # 尝试从错误信息中提取 JSON 字符串并修复
        error_msg = str(e)
        partial_data = {}
        
        if "Function Structure arguments:" in error_msg:
            try:
                # 提取 JSON 字符串
                json_str = error_msg.split("Function Structure arguments:", 1)[1].strip().split('are not valid JSON')[0].strip()
                # 预处理 LaTeX 数学符号 - 使用四个反斜杠来确保正确转义
                json_str = json_str.replace('\\', '\\\\')
                # 尝试解析修复后的 JSON
                partial_data = json.loads(json_str)
            except Exception as json_e:
                print(f"Failed to parse JSON for {item.get('id', 'unknown')}: {json_e}", file=sys.stderr)
        
        # Merge partial data with defaults to ensure all fields exist
        item['AI'] = {**defaults, **partial_data}
        print(f"Using partial AI data for {item.get('id', 'unknown')}: {list(partial_data.keys())}", file=sys.stderr)
    except Exception as e:
        # Catch any other exceptions and provide default values
        print(f"Unexpected error for {item.get('id', 'unknown')}: {e}", file=sys.stderr)
        item['AI'] = defaults
    
    # Final validation to ensure all required fields exist
    for field in defaults.keys():
        if field not in item['AI']:
            item['AI'][field] = defaults[field]

    # 检查 AI 生成的所有字段
    for v in item.get("AI", {}).values():
        if is_sensitive(str(v)):
            return None
    return item

def process_all_items(data: List[Dict], provider: str, model_name: str, language: str, max_workers: int) -> List[Dict]:
    """并行处理所有数据项"""
    enhancer = build_enhancer(provider, model_name)
    print('Connect to:', f"{provider}/{model_name}", file=sys.stderr)
    
    # 使用线程池并行处理
    processed_data = [None] * len(data)  # 预分配结果列表
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_idx = {
            executor.submit(process_single_item, enhancer, item, language): idx
            for idx, item in enumerate(data)
        }
        
        # 使用tqdm显示进度
        for future in tqdm(
            as_completed(future_to_idx),
            total=len(data),
            desc="Processing items"
        ):
            idx = future_to_idx[future]
            try:
                result = future.result()
                processed_data[idx] = result
            except Exception as e:
                print(f"Item at index {idx} generated an exception: {e}", file=sys.stderr)
                # Add default AI fields to ensure consistency
                processed_data[idx] = data[idx]
                processed_data[idx]['AI'] = {
                    "tldr": "Processing failed",
                    "motivation": "Processing failed",
                    "method": "Processing failed",
                    "result": "Processing failed",
                    "conclusion": "Processing failed",
                    "detailed_summary": "Processing failed"
                }
    
    return processed_data

def main():
    args = parse_args()
    provider = (os.environ.get("AI_PROVIDER") or "trapi").strip().lower()
    if provider == "openai":
        model_name = os.environ.get("MODEL_NAME") or 'deepseek-chat'
    else:
        model_name = os.environ.get("TRAPI_MODEL") or 'gpt-5.4-mini_2026-03-17'
    language = os.environ.get("LANGUAGE") or 'Chinese'

    # 检查并删除目标文件
    target_file = args.data.replace('.jsonl', f'_AI_enhanced_{language}.jsonl')
    if os.path.exists(target_file):
        os.remove(target_file)
        print(f'Removed existing file: {target_file}', file=sys.stderr)

    # 读取数据
    data = []
    with open(args.data, "r") as f:
        for line in f:
            data.append(json.loads(line))

    # 去重
    seen_ids = set()
    unique_data = []
    for item in data:
        if item['id'] not in seen_ids:
            seen_ids.add(item['id'])
            unique_data.append(item)

    data = unique_data
    print('Open:', args.data, file=sys.stderr)
    
    # 并行处理所有数据
    processed_data = process_all_items(
        data,
        provider,
        model_name,
        language,
        args.max_workers
    )
    
    # 保存结果
    with open(target_file, "w") as f:
        for item in processed_data:
            if item is not None:
                f.write(json.dumps(item) + "\n")

if __name__ == "__main__":
    main()
