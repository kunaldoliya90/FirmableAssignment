# Turn hierarchy nodes into Position records with canonical titles from the taxonomy
from __future__ import annotations

from orggraph_dataset.generators.hierarchy_generator import OrgNode, OrgTree
from orggraph_dataset.schemas import Position, SeniorityLevel
from orggraph_dataset.taxonomy import CanonicalTitle, TitleTaxonomy
from orggraph_dataset.utils.ids import position_id


def title_for_node(taxonomy: TitleTaxonomy, node: OrgNode) -> CanonicalTitle:
    if node.exec_role is not None:
        return taxonomy.executive_title(node.exec_role)
    return taxonomy.title_for(node.family, node.seniority)


def generate_positions(
    company_index: int, company_id: str, tree: OrgTree, taxonomy: TitleTaxonomy
) -> tuple[list[Position], list[CanonicalTitle]]:
    ids = [position_id(company_index, i + 1) for i in range(len(tree.nodes))]
    positions: list[Position] = []
    titles: list[CanonicalTitle] = []
    for node in tree.nodes:
        title = title_for_node(taxonomy, node)
        titles.append(title)
        positions.append(
            Position(
                position_id=ids[node.index],
                company_id=company_id,
                department_id=node.department.department_id,
                canonical_title=title.canonical_title,
                job_family=title.job_family,
                seniority_level=SeniorityLevel(title.seniority_level),
                organizational_level=node.depth,
                parent_position_id=ids[node.parent] if node.parent is not None else None,
            )
        )
    return positions, titles
