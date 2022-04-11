from torch_geometric.transforms import RandomLinkSplit
from torch_geometric.data import HeteroData
from data.types import DataLoaderConfig, ArticleIdMap, CustomerIdMap
import torch
import json
from typing import Tuple
import torch_geometric.transforms as T
from torch_geometric.loader import LinkNeighborLoader


def create_dataloaders(
    config: DataLoaderConfig,
) -> Tuple[LinkNeighborLoader, HeteroData, HeteroData, CustomerIdMap, ArticleIdMap]:
    data = torch.load("data/derived/graph.pt")
    # Add a reverse ('article', 'rev_buys', 'customer') relation for message passing:
    data = T.ToUndirected()(data)
    del data["article", "rev_buys", "customer"].edge_label  # type: ignore # Remove "reverse" label.

    transform = RandomLinkSplit(
        is_undirected=True,
        add_negative_train_samples=False,
        num_val=config.val_split,
        num_test=config.test_split,
        neg_sampling_ratio=0,
        edge_types=[("customer", "buys", "article")],
        rev_edge_types=[("article", "rev_buys", "customer")],
    )
    train_split, val_split, test_split = transform(data)

    # Confirm that every node appears in every set above
    assert (
        train_split.num_nodes == val_split.num_nodes
        and train_split.num_nodes == test_split.num_nodes
    )

    customer_id_map = read_json("data/derived/customer_id_map_forward.json")
    article_id_map = read_json("data/derived/article_id_map_forward.json")

    input_node_type = ("customer", torch.ones((data["customer"].num_nodes)))
    return (
        LinkNeighborLoader(
            train_split,
            batch_size=config.batch_size,
            num_neighbors=[5],  # {data.edge_types[0]: [5]},
            shuffle=True,
            directed=False,
            edge_label_index=(
                train_split.edge_stores[0],
                train_split[train_split.edge_types[0]].edge_label_index,
            ),
            edge_label=torch.ones(train_split.edge_stores[0].edge_index.size(1)),
        ),
        val_split,
        test_split,
        customer_id_map,
        article_id_map,
    )  # type: ignore


def create_datasets(
    config: DataLoaderConfig,
) -> Tuple[HeteroData, HeteroData, HeteroData, CustomerIdMap, ArticleIdMap]:
    data = torch.load("data/derived/graph.pt")
    # Add a reverse ('article', 'rev_buys', 'customer') relation for message passing:
    undirected_transformer = T.ToUndirected()
    data = undirected_transformer(data)
    del data["article", "rev_buys", "customer"].edge_label  # type: ignore # Remove "reverse" label.

    transform = RandomLinkSplit(
        is_undirected=True,
        add_negative_train_samples=False,
        num_val=config.val_split,
        num_test=config.test_split,
        neg_sampling_ratio=0,
        edge_types=[("customer", "buys", "article")],
        rev_edge_types=[("article", "rev_buys", "customer")],
    )
    train_split, val_split, test_split = transform(data)

    # Confirm that every node appears in every set above
    assert (
        train_split.num_nodes == val_split.num_nodes
        and train_split.num_nodes == test_split.num_nodes
    )

    customer_id_map = read_json("data/derived/customer_id_map_forward.json")
    article_id_map = read_json("data/derived/article_id_map_forward.json")

    return (
        train_split,
        val_split,
        test_split,
        customer_id_map,
        article_id_map,
    )  # type: ignore


def read_json(filename: str):
    with open(filename) as f_in:
        return json.load(f_in)
