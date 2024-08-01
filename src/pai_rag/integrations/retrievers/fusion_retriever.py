import asyncio
from enum import Enum
from typing import Dict, List, Optional, Tuple, cast, Any

from llama_index.core.async_utils import run_async_tasks
from llama_index.core.callbacks.base import CallbackManager
from llama_index.core.constants import DEFAULT_SIMILARITY_TOP_K
from llama_index.core.llms.utils import LLMType, resolve_llm
from llama_index.core.prompts import PromptTemplate
from llama_index.core.prompts.mixin import PromptDictType
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import (
    IndexNode,
    NodeWithScore,
    QueryBundle,
    BaseComponent,
    BaseNode,
    TextNode,
    MetadataMode,
)
from llama_index.core.settings import Settings
from llama_index.core.utils import print_text

QUERY_GEN_PROMPT = (
    "You are a helpful assistant that generates multiple search queries based on a "
    "single input query. Generate {num_queries} search queries, one on each line, "
    "related to the following input query:\n"
    "Query: {query}\n"
    "Queries:\n"
)


class FUSION_MODES(str, Enum):
    """Enum for different fusion modes."""

    RECIPROCAL_RANK = "reciprocal_rerank"  # apply reciprocal rank fusion
    DETAIL_RECIPROCAL_RANK = "detail_reciprocal_rerank"  # apply reciprocal rank fusion
    RELATIVE_SCORE = "relative_score"  # apply relative score fusion
    DIST_BASED_SCORE = "dist_based_score"  # apply distance-based score fusion
    SIMPLE = "simple"  # simple re-ordering of results based on original scores
    NO_FUSION = "no_fusion"


class MyNodeWithScore(BaseComponent):
    node: BaseNode
    score: Optional[float] = None
    retriever_type: Optional[str] = None

    def __str__(self) -> str:
        score_str = "None" if self.score is None else f"{self.score: 0.3f}"
        return f"{self.node}\nScore: {score_str}\nRetrieverType: {self.retriever_type}"

    def get_score(self, raise_error: bool = False) -> float:
        """Get score."""
        if self.score is None:
            if raise_error:
                raise ValueError("Score not set.")
            else:
                return 0.0
        else:
            return self.score

    @classmethod
    def class_name(cls) -> str:
        return "MyNodeWithScore"

    ##### pass through methods to BaseNode #####
    @property
    def node_id(self) -> str:
        return self.node.node_id

    @property
    def id_(self) -> str:
        return self.node.id_

    @property
    def text(self) -> str:
        if isinstance(self.node, TextNode):
            return self.node.text
        else:
            raise ValueError("Node must be a TextNode to get text.")

    @property
    def metadata(self) -> Dict[str, Any]:
        return self.node.metadata

    @property
    def embedding(self) -> Optional[List[float]]:
        return self.node.embedding

    def get_text(self) -> str:
        if isinstance(self.node, TextNode):
            return self.node.get_text()
        else:
            raise ValueError("Node must be a TextNode to get text.")

    def get_content(self, metadata_mode: MetadataMode = MetadataMode.NONE) -> str:
        return self.node.get_content(metadata_mode=metadata_mode)

    def get_embedding(self) -> List[float]:
        return self.node.get_embedding()


class MyQueryFusionRetriever(BaseRetriever):
    def __init__(
        self,
        retrievers: List[BaseRetriever],
        llm: Optional[LLMType] = None,
        query_gen_prompt: Optional[str] = None,
        mode: FUSION_MODES = FUSION_MODES.NO_FUSION,
        similarity_top_k: int = DEFAULT_SIMILARITY_TOP_K,
        num_queries: int = 4,
        use_async: bool = True,
        verbose: bool = False,
        callback_manager: Optional[CallbackManager] = None,
        objects: Optional[List[IndexNode]] = None,
        object_map: Optional[dict] = None,
        retriever_weights: Optional[List[float]] = None,
    ) -> None:
        self.num_queries = num_queries
        self.query_gen_prompt = query_gen_prompt or QUERY_GEN_PROMPT
        self.similarity_top_k = similarity_top_k
        self.mode = mode
        self.use_async = use_async

        self._retrievers = retrievers
        if retriever_weights is None:
            self._retriever_weights = [1.0 / len(retrievers)] * len(retrievers)
        else:
            # Sum of retriever_weights must be 1
            total_weight = sum(retriever_weights)
            self._retriever_weights = [w / total_weight for w in retriever_weights]
        self._llm = (
            resolve_llm(llm, callback_manager=callback_manager) if llm else Settings.llm
        )
        super().__init__(
            callback_manager=callback_manager,
            object_map=object_map,
            objects=objects,
            verbose=verbose,
        )

    def _get_prompts(self) -> PromptDictType:
        """Get prompts."""
        return {"query_gen_prompt": PromptTemplate(self.query_gen_prompt)}

    def _update_prompts(self, prompts: PromptDictType) -> None:
        """Update prompts."""
        if "query_gen_prompt" in prompts:
            self.query_gen_prompt = cast(
                PromptTemplate, prompts["query_gen_prompt"]
            ).template

    def _get_queries(self, original_query: str) -> List[QueryBundle]:
        prompt_str = self.query_gen_prompt.format(
            num_queries=self.num_queries - 1,
            query=original_query,
        )
        response = self._llm.complete(prompt_str)

        # assume LLM proper put each query on a newline
        queries = response.text.split("\n")
        queries = [q.strip() for q in queries if q.strip()]
        if self._verbose:
            queries_str = "\n".join(queries)
            print(f"Generated queries:\n{queries_str}")

        # The LLM often returns more queries than we asked for, so trim the list.
        return [QueryBundle(q) for q in queries[: self.num_queries - 1]]

    def _reciprocal_rerank_fusion(
        self, results: Dict[Tuple[str, int], List[NodeWithScore]]
    ) -> List[MyNodeWithScore]:
        """
        Apply reciprocal rank fusion.

        The original paper uses k=60 for best results:
        https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
        """
        k = 60.0  # `k` is a parameter used to control the impact of outlier rankings.
        fused_scores = {}
        text_to_node = {}

        # compute reciprocal rank scores
        for nodes_with_scores in results.values():
            for rank, node_with_score in enumerate(
                sorted(nodes_with_scores, key=lambda x: x.score or 0.0, reverse=True)
            ):
                text = node_with_score.node.get_content()
                text_to_node[text] = node_with_score
                if text not in fused_scores:
                    fused_scores[text] = 0.0
                fused_scores[text] += 1.0 / (rank + k)

        # sort results
        reranked_results = dict(
            sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
        )

        # adjust node scores
        reranked_nodes: List[MyNodeWithScore] = []
        for text, score in reranked_results.items():
            reranked_nodes.append(text_to_node[text])
            reranked_nodes[-1].score = score

        return reranked_nodes

    def _relative_score_fusion(
        self,
        results: Dict[Tuple[str, int], List[NodeWithScore]],
        dist_based: Optional[bool] = False,
    ) -> List[NodeWithScore]:
        """Apply relative score fusion."""
        # MinMax scale scores of each result set (highest value becomes 1, lowest becomes 0)
        # then scale by the weight of the retriever
        min_max_scores = {}
        for query_tuple, nodes_with_scores in results.items():
            if not nodes_with_scores:
                min_max_scores[query_tuple] = (0.0, 0.0)
                continue
            scores = [node_with_score.score for node_with_score in nodes_with_scores]
            if dist_based:
                # Set min and max based on mean and std dev
                mean_score = sum(scores) / len(scores)
                std_dev = (
                    sum((x - mean_score) ** 2 for x in scores) / len(scores)
                ) ** 0.5
                min_score = mean_score - 3 * std_dev
                max_score = mean_score + 3 * std_dev
            else:
                min_score = min(scores)
                max_score = max(scores)
            min_max_scores[query_tuple] = (min_score, max_score)

        for query_tuple, nodes_with_scores in results.items():
            for node_with_score in nodes_with_scores:
                min_score, max_score = min_max_scores[query_tuple]
                # Scale the score to be between 0 and 1
                if max_score == min_score:
                    node_with_score.score = 1.0 if max_score > 0 else 0.0
                else:
                    node_with_score.score = (node_with_score.score - min_score) / (
                        max_score - min_score
                    )
                # Scale by the weight of the retriever
                retriever_idx = query_tuple[1]
                node_with_score.score *= self._retriever_weights[retriever_idx]
                # Divide by the number of queries
                node_with_score.score /= self.num_queries

        # Use a dict to de-duplicate nodes
        all_nodes: Dict[str, NodeWithScore] = {}

        # Sum scores for each node
        for nodes_with_scores in results.values():
            for node_with_score in nodes_with_scores:
                text = node_with_score.node.get_content()
                if text in all_nodes:
                    all_nodes[text].score += node_with_score.score
                else:
                    all_nodes[text] = node_with_score

        return sorted(all_nodes.values(), key=lambda x: x.score or 0.0, reverse=True)

    def _simple_fusion(
        self, results: Dict[Tuple[str, int], List[NodeWithScore]]
    ) -> List[NodeWithScore]:
        """Apply simple fusion."""
        # Use a dict to de-duplicate nodes
        all_nodes: Dict[str, NodeWithScore] = {}
        for nodes_with_scores in results.values():
            for node_with_score in nodes_with_scores:
                text = node_with_score.node.get_content()
                if text in all_nodes:
                    max_score = max(node_with_score.score, all_nodes[text].score)
                    all_nodes[text].score = max_score
                else:
                    all_nodes[text] = node_with_score

        return sorted(all_nodes.values(), key=lambda x: x.score or 0.0, reverse=True)

    def _no_fusion(
        self, results: Dict[Tuple[str, int], List[NodeWithScore]]
    ) -> List[MyNodeWithScore]:
        """Apply simple fusion."""
        # Use a dict to de-duplicate nodes
        all_nodes: List[NodeWithScore] = []
        for nodes_with_scores in results.values():
            for node_with_score in nodes_with_scores:
                all_nodes.append(node_with_score)
        return all_nodes

    def _run_nested_async_queries(
        self, queries: List[QueryBundle]
    ) -> Dict[Tuple[str, int], List[NodeWithScore]]:
        tasks, task_queries = [], []
        for query in queries:
            for i, retriever in enumerate(self._retrievers):
                tasks.append(retriever.aretrieve(query))
                task_queries.append((query.query_str, i))

        task_results = run_async_tasks(tasks)

        results = {}
        for query_tuple, query_result in zip(task_queries, task_results):
            results[query_tuple] = query_result

        return results

    async def _run_async_queries(
        self, queries: List[QueryBundle]
    ) -> Dict[Tuple[str, int], List[NodeWithScore]]:
        tasks, task_queries = [], []
        for query in queries:
            for i, retriever in enumerate(self._retrievers):
                tasks.append(retriever.aretrieve(query))
                task_queries.append((query.query_str, i))

        task_results = await asyncio.gather(*tasks)

        results = {}
        for query_tuple, query_result in zip(task_queries, task_results):
            results[query_tuple] = query_result

        return results

    def _run_sync_queries(
        self, queries: List[QueryBundle]
    ) -> Dict[Tuple[str, int], List[NodeWithScore]]:
        results = {}
        for query in queries:
            for i, retriever in enumerate(self._retrievers):
                results[(query.query_str, i)] = retriever.retrieve(query)

        return results

    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        queries: List[QueryBundle] = [query_bundle]
        if self.num_queries > 1:
            queries.extend(self._get_queries(query_bundle.query_str))

        if self.use_async:
            results = self._run_nested_async_queries(queries)
        else:
            results = self._run_sync_queries(queries)

        if self.mode == FUSION_MODES.RECIPROCAL_RANK:
            return self._reciprocal_rerank_fusion(results)[: self.similarity_top_k]
        elif self.mode == FUSION_MODES.RELATIVE_SCORE:
            return self._relative_score_fusion(results)[: self.similarity_top_k]
        elif self.mode == FUSION_MODES.DIST_BASED_SCORE:
            return self._relative_score_fusion(results, dist_based=True)[
                : self.similarity_top_k
            ]
        elif self.mode == FUSION_MODES.SIMPLE:
            return self._simple_fusion(results)[: self.similarity_top_k]
        elif self.mode == FUSION_MODES.NO_FUSION:
            return self._no_fusion(results)
        else:
            raise ValueError(f"Invalid fusion mode: {self.mode}")

    async def _aretrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        queries: List[QueryBundle] = [query_bundle]
        if self.num_queries > 1:
            queries.extend(self._get_queries(query_bundle.query_str))

        results = await self._run_async_queries(queries)

        if self.mode == FUSION_MODES.RECIPROCAL_RANK:
            return self._reciprocal_rerank_fusion(results)[: self.similarity_top_k]
        elif self.mode == FUSION_MODES.RELATIVE_SCORE:
            return self._relative_score_fusion(results)[: self.similarity_top_k]
        elif self.mode == FUSION_MODES.DIST_BASED_SCORE:
            return self._relative_score_fusion(results, dist_based=True)[
                : self.similarity_top_k
            ]
        elif self.mode == FUSION_MODES.SIMPLE:
            return self._simple_fusion(results)[: self.similarity_top_k]
        elif self.mode == FUSION_MODES.NO_FUSION:
            return self._no_fusion(results)
        else:
            raise ValueError(f"Invalid fusion mode: {self.mode}")

    async def _ahandle_recursive_retrieval(
        self, query_bundle: QueryBundle, nodes: List[NodeWithScore]
    ) -> List[NodeWithScore]:
        retrieved_nodes: List[NodeWithScore] = []
        for n in nodes:
            node = n.node
            score = n.score or 1.0
            if isinstance(node, IndexNode):
                obj = node.obj or self.object_map.get(node.index_id, None)
                if obj is not None:
                    if self._verbose:
                        print_text(
                            f"Retrieval entering {node.index_id}: {obj.__class__.__name__}\n",
                            color="llama_turquoise",
                        )
                    # TODO: Add concurrent execution via `run_jobs()` ?
                    retrieved_nodes.extend(
                        await self._aretrieve_from_object(
                            obj, query_bundle=query_bundle, score=score
                        )
                    )
                else:
                    retrieved_nodes.append(n)
            else:
                retrieved_nodes.append(n)

        return retrieved_nodes