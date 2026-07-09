from pydantic import BaseModel, Field, field_validator
import re

class Structure(BaseModel):
    tldr: str = Field(description="generate a too long; didn't read summary")
    motivation: str = Field(description="describe the motivation in this paper")
    method: str = Field(description="method of this paper")
    result: str = Field(description="result of this paper")
    conclusion: str = Field(description="conclusion of this paper")
    detailed_summary: str = Field(description="用目标语言分点详细总结这篇论文：1. 解决了什么问题；2. 有哪些相关工作；3. 采用了什么研究方法；4. 做了哪些实验、结果如何；5. 结论是什么；最后整体总结这篇文章的核心内容")