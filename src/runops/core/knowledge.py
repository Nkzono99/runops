"""Knowledge layer: local insights and structured facts."""

from __future__ import annotations

from runops.core import _knowledge_facts as knowledge_facts
from runops.core import _knowledge_insights as knowledge_insights
from runops.core import _knowledge_paths as knowledge_paths
from runops.core.models import knowledge as knowledge_records

Insight = knowledge_records.Insight
Fact = knowledge_records.Fact

INSIGHT_TYPES = knowledge_insights.INSIGHT_TYPES
FACT_TYPES = knowledge_facts.FACT_TYPES

get_runops_dir = knowledge_paths.get_runops_dir
get_insights_dir = knowledge_paths.get_insights_dir
get_knowledge_dir = knowledge_paths.get_knowledge_dir
get_candidate_facts_dir = knowledge_paths.get_candidate_facts_dir

parse_insight = knowledge_insights.parse_insight
write_insight = knowledge_insights.write_insight
list_insights = knowledge_insights.list_insights

load_facts_file = knowledge_facts.load_facts_file
load_facts = knowledge_facts.load_facts
load_candidate_facts = knowledge_facts.load_candidate_facts
save_fact = knowledge_facts.save_fact
next_fact_id = knowledge_facts.next_fact_id
promote_candidate_fact = knowledge_facts.promote_candidate_fact
query_facts = knowledge_facts.query_facts
