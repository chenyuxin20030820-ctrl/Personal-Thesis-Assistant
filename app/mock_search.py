"""Deterministic demo records. None represents a real publication."""

import re

TOPICS = [
    ("数字金融与制造业高质量发展", "Digital Finance and High-Quality Manufacturing Development", ["数字金融", "制造业", "金融科技", "digital finance", "manufacturing"], "评估数字金融对制造业企业质量提升的影响"),
    ("人工智能与科研效率", "Artificial Intelligence and Research Productivity", ["人工智能", "科研", "ai", "artificial intelligence", "research"], "分析人工智能工具对科研流程和产出的作用"),
    ("绿色创新与碳减排", "Green Innovation and Carbon Reduction", ["绿色创新", "碳减排", "低碳", "green innovation", "carbon"], "考察绿色技术创新与碳排放变化的关系"),
    ("全球供应链韧性", "Global Supply Chain Resilience", ["供应链", "韧性", "supply chain", "resilience"], "识别供应链冲击下企业的恢复机制"),
    ("乡村振兴与数字普惠金融", "Rural Revitalization and Financial Inclusion", ["乡村振兴", "普惠金融", "农村", "rural", "financial inclusion"], "研究数字金融服务与乡村发展之间的联系"),
    ("教育技术与学习成效", "Educational Technology and Learning Outcomes", ["教育", "学习", "教学", "education", "learning"], "评估教育技术应用对学习成效的影响"),
    ("公共卫生与医疗资源配置", "Public Health and Healthcare Resource Allocation", ["公共卫生", "医疗", "健康", "public health", "healthcare"], "分析医疗资源配置与服务可及性的关系"),
    ("国际贸易与企业创新", "International Trade and Firm Innovation", ["国际贸易", "出口", "企业创新", "trade", "export", "innovation"], "探讨贸易开放与企业创新活动之间的关系"),
    ("机器学习与经济预测", "Machine Learning in Economic Forecasting", ["机器学习", "经济预测", "预测", "machine learning", "forecasting"], "比较机器学习方法在经济预测中的表现"),
    ("平台经济与劳动市场", "Platform Economy and Labor Markets", ["平台经济", "劳动市场", "就业", "platform economy", "labor"], "研究平台经济对就业结构的影响"),
    ("城市治理与智慧交通", "Urban Governance and Smart Mobility", ["城市治理", "智慧交通", "交通", "urban", "mobility"], "评估智慧交通技术对城市治理的作用"),
    ("企业ESG与融资约束", "Corporate ESG and Financing Constraints", ["esg", "融资约束", "企业治理", "financing constraints"], "考察企业ESG表现与融资约束的关联"),
]

VARIANTS = [
    ("的影响机制研究", "Evidence on Impact Mechanisms", "固定效应回归与机制检验", "构造地区与年份面板，先估计基准模型，再检验中介路径"),
    ("：来自面板数据的证据", "Panel Data Evidence", "双向固定效应模型", "按年份整理模拟面板样本，控制个体和时间效应并进行稳健性检验"),
    ("：政策试点的准自然实验", "A Quasi-Experimental Study", "双重差分法", "将模拟试点组与对照组在政策前后比较，并检查平行趋势"),
    ("：异质性与区域差异", "Heterogeneity Across Regions", "分组回归与交互项分析", "按地区和企业特征划分模拟样本，比较不同组别的估计结果"),
    ("：理论框架与案例比较", "A Comparative Case Study", "多案例比较分析", "选取三个模拟案例，按共同维度编码并比较机制差异"),
    ("：测量方法与研究展望", "Measurement and Future Directions", "文献综述与指标比较", "汇总模拟研究中的指标定义，比较适用条件并梳理后续问题"),
    ("：企业层面的经验证据", "Firm-Level Evidence", "企业面板回归", "整理模拟企业年度指标，估计主效应并比较行业差异"),
    ("：空间溢出效应分析", "Spatial Spillover Effects", "空间杜宾模型", "构建模拟区域邻接矩阵，比较本地效应与邻近地区的间接效应"),
    ("：政策冲击与动态调整", "Policy Shocks and Dynamic Adjustment", "事件研究法", "围绕模拟政策实施年份设置事件窗口，绘制动态系数并进行安慰剂检验"),
    ("：微观调查数据分析", "Evidence from Survey Data", "问卷统计与多元回归", "对模拟问卷样本进行缺失值处理、信度检查和回归估计"),
    ("：机制识别与稳健性检验", "Mechanisms and Robustness", "工具变量与稳健性检验", "对模拟内生性问题设置工具变量，并比较替代指标的估计结果"),
    ("：跨地区比较研究", "A Cross-Regional Comparison", "区域比较与匹配方法", "匹配特征相近的模拟地区，比较不同政策环境下的结果"),
]


def build_records():
    papers = []
    for source in ("CNKI", "Google Scholar"):
        for topic_index, (cn, en, aliases, purpose) in enumerate(TOPICS):
            for variant_index, (cn_suffix, en_suffix, method, process) in enumerate(VARIANTS):
                number = topic_index * len(VARIANTS) + variant_index + 1
                year = 2020 + (topic_index + variant_index) % 7
                rich = variant_index % 3 != 1
                title = cn + cn_suffix if source == "CNKI" else en + ": " + en_suffix
                if rich:
                    abstract = f"本地模拟摘要：本文旨在{purpose}。研究采用{method}。实证过程为：{process}。结果仅为界面演示数据，不代表真实研究结论。"
                    method_text, process_text = method, process
                else:
                    abstract = f"本地模拟摘要：本文旨在{purpose}，讨论相关研究背景与可能机制。模拟摘要未给出具体方法、样本或实证步骤。"
                    method_text, process_text = "模拟摘要未提供具体研究方法，无法判断。", "模拟摘要未提供样本、模型或实证步骤，无法判断。"
                papers.append({
                    "id": f"{'CN' if source == 'CNKI' else 'GS'}-MOCK-{number:03d}",
                    "source": source,
                    "is_mock": True,
                    "title": title,
                    "year": year,
                    "authors": "示例作者甲、示例作者乙" if source == "CNKI" else "Demo Author A; Demo Author B",
                    "venue": "模拟学术资料" if source == "CNKI" else "Synthetic Research Collection",
                    "document_type": "期刊论文" if variant_index < 9 else "研究报告",
                    "doi": None,
                    "url": None,
                    "pdf_url": None,
                    "abstract": abstract,
                    "analysis": {
                        "summary": abstract.removeprefix("本地模拟摘要："),
                        "purpose": purpose,
                        "method": method_text,
                        "empirical_process": process_text,
                        "basis": "本地模拟摘要（演示数据，并非真实论文）",
                    },
                    "_aliases": aliases,
                })
    return papers


PAPERS = build_records()


def score(paper, query):
    q = query.casefold().strip()
    title = paper["title"].casefold()
    alias_matches = 0
    for alias in paper["_aliases"]:
        a = alias.casefold()
        if a in q or (len(q) >= 2 and q in a):
            alias_matches += 1
    if alias_matches:
        return alias_matches * 12
    value = 20 if q in title else 0
    for word in [w for w in re.split(r"[\s,，/、与和的及：:]+", q) if len(w) >= 2]:
        if word in title or any(word in a.casefold() for a in paper["_aliases"]):
            value += 3
    return value


def search_mock_papers(query, sources, year_from, year_to, limit, sort="relevance"):
    candidates = []
    for paper in PAPERS:
        if paper["source"] not in sources or not year_from <= paper["year"] <= year_to:
            continue
        relevance = score(paper, query)
        if relevance:
            public = {key: value for key, value in paper.items() if not key.startswith("_")}
            public["relevance_score"] = relevance
            candidates.append(public)
    if sort == "year_asc":
        candidates.sort(key=lambda p: (p["year"], -p["relevance_score"], p["id"]))
    elif sort == "year_desc":
        candidates.sort(key=lambda p: (-p["year"], -p["relevance_score"], p["id"]))
    else:
        candidates.sort(key=lambda p: (-p["relevance_score"], -p["year"], p["id"]))
    return {"total": len(candidates), "returned": min(limit, len(candidates)), "items": candidates[:limit], "mock": True}
