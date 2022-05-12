import pandas as pd
import matplotlib.pyplot as plt

import torch as t
from torch import optim
from tqdm import tqdm

from torch_geometric.utils import structured_negative_sampling

from torch_geometric.typing import Adj
from model.lightgcn import LightGCN
from data.lightgcn_loader import create_dataloaders_lightgcn, sample_mini_batch
from utils.metrics_lightgcn import (
    get_metrics_lightgcn,
    bpr_loss,
    RecallPrecision_ATk,
    NDCGatK_r,
    get_user_positive_items,
)

from config import Config, lightgcn_config


# wrapper function to evaluate model
def evaluation(
    model, edge_index, sparse_edge_index, exclude_edge_indices, k, lambda_val
):
    """Evaluates model loss and metrics including recall, precision, ndcg @ k

    Args:
        model (LighGCN): lightgcn model
        edge_index (t.Tensor): 2 by N list of edges for split to evaluate
        sparse_edge_index (sparseTensor): sparse adjacency matrix for split to evaluate
        exclude_edge_indices ([type]): 2 by N list of edges for split to discount from evaluation
        k (int): determines the top k items to compute metrics on
        lambda_val (float): determines lambda for bpr loss

    Returns:
        tuple: bpr loss, recall @ k, precision @ k, ndcg @ k
    """
    # get embeddings
    users_emb_final, users_emb_0, items_emb_final, items_emb_0 = model.forward(
        sparse_edge_index
    )
    edges = structured_negative_sampling(
        edge_index.to("cpu"),
        num_nodes=t.max(edge_index[1]).to("cpu"),
        contains_neg_self_loops=False,
    )
    user_indices, pos_item_indices, neg_item_indices = edges[0], edges[1], edges[2]
    users_emb_final, users_emb_0 = (
        users_emb_final[user_indices],
        users_emb_0[user_indices],
    )
    pos_items_emb_final, pos_items_emb_0 = (
        items_emb_final[pos_item_indices],
        items_emb_0[pos_item_indices],
    )
    neg_items_emb_final, neg_items_emb_0 = (
        items_emb_final[neg_item_indices],
        items_emb_0[neg_item_indices],
    )

    loss = bpr_loss(
        users_emb_final,
        users_emb_0,
        pos_items_emb_final,
        pos_items_emb_0,
        neg_items_emb_final,
        neg_items_emb_0,
        lambda_val,
    ).item()

    recall, precision, ndcg = get_metrics_lightgcn(
        model, edge_index, exclude_edge_indices, k
    )

    return loss, recall, precision, ndcg


def train(config: Config):
    config.print()
    (
        train_sparse_edge_index,
        val_sparse_edge_index,
        test_sparse_edge_index,
        train_edge_index,
        val_edge_index,
        test_edge_index,
        edge_index,
        user_mapping_index,
        article_mapping_index,
        user_mapping_id,
        article_mapping_id,
        num_users,
        num_articles,
    ) = create_dataloaders_lightgcn()

    # setup
    device = "cpu"
    print(f"Using device {device}.")

    model = LightGCN(
        num_users,
        num_articles,
        embedding_dim=config.hidden_layer_size,
        K=config.num_gnn_layers,
    )
    model = model.to(device)
    model.train()

    optimizer = optim.Adam(model.parameters(), lr=config.learning_rate)
    scheduler = optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.95)

    edge_index = edge_index.to(device)
    train_edge_index = train_edge_index.to(device)
    train_sparse_edge_index = train_sparse_edge_index.to(device)

    val_edge_index = val_edge_index.to(device)
    val_sparse_edge_index = val_sparse_edge_index.to(device)

    # training loop
    train_losses = []
    val_losses = []

    loop_obj = tqdm(range(0, config.epochs))
    for iter in loop_obj:
        # for iter in range(config.epochs):
        # forward propagation
        users_emb_final, users_emb_0, items_emb_final, items_emb_0 = model.forward(
            train_sparse_edge_index
        )

        # mini batching
        user_indices, pos_item_indices, neg_item_indices = sample_mini_batch(
            config.batch_size, train_edge_index
        )
        user_indices, pos_item_indices, neg_item_indices = (
            user_indices.to(device),
            pos_item_indices.to(device),
            neg_item_indices.to(device),
        )
        users_emb_final, users_emb_0 = (
            users_emb_final[user_indices],
            users_emb_0[user_indices],
        )
        pos_items_emb_final, pos_items_emb_0 = (
            items_emb_final[pos_item_indices],
            items_emb_0[pos_item_indices],
        )
        neg_items_emb_final, neg_items_emb_0 = (
            items_emb_final[neg_item_indices],
            items_emb_0[neg_item_indices],
        )

        # loss computation
        train_loss = bpr_loss(
            users_emb_final,
            users_emb_0,
            pos_items_emb_final,
            pos_items_emb_0,
            neg_items_emb_final,
            neg_items_emb_0,
            config.Lambda,
        )

        optimizer.zero_grad()
        train_loss.backward()
        optimizer.step()

        if iter % config.eval_every == 0:
            model.eval()
            val_loss, recall, precision, ndcg = evaluation(
                model,
                val_edge_index,
                val_sparse_edge_index,
                [train_edge_index],
                config.k,
                config.Lambda,
            )
            print(
                f"[Iteration {iter}/{config.epochs}] train_loss: {round(train_loss.item(), 5)}, val_loss: {round(val_loss, 5)}, val_recall@{config.k}: {round(recall, 5)}, val_precision@{config.k}: {round(precision, 5)}, val_ndcg@{config.k}: {round(ndcg, 5)}"
            )
            train_losses.append(train_loss.item())
            val_losses.append(val_loss)
            model.train()

        if iter % config.lr_decay_every == 0 and iter != 0:
            scheduler.step()

    iters = [iter * config.eval_every for iter in range(len(train_losses))]
    plt.plot(iters, train_losses, label="train")
    plt.plot(iters, val_losses, label="validation")
    plt.xlabel("iteration")
    plt.ylabel("loss")
    plt.title("training and validation loss curves")
    plt.legend()
    plt.show()

    # evaluate on test set
    model.eval()
    test_edge_index = test_edge_index.to(device)
    test_sparse_edge_index = test_sparse_edge_index.to(device)

    test_loss, test_recall, test_precision, test_ndcg = evaluation(
        model,
        test_edge_index,
        test_sparse_edge_index,
        [train_edge_index, val_edge_index],
        config.k,
        config.Lambda,
    )

    print(
        f"[test_loss: {round(test_loss, 5)}, test_recall@{config.k}: {round(test_recall, 5)}, test_precision@{config.k}: {round(test_precision, 5)}, test_ndcg@{config.k}: {round(test_ndcg, 5)}"
    )

    """# Make New Recommendatios for a Given User"""

    model.eval()

    user_pos_items = get_user_positive_items(edge_index)

    def save_scores():
        # user = user_mapping_index[user_id]
        user_embeddings = model.users_emb.weight  # [user]
        item_embeddings = model.items_emb.weight
        # scores = model.items_emb.weight @ e_u

        print("| Saving the user and article final embeddings...")
        t.save(user_embeddings, "data/derived/users_emb_final_lightgcn.pt")
        t.save(item_embeddings, "data/derived/items_emb_final_lightgcn.pt")

    save_scores()

    def make_predictions(user_id, num_recs):
        user = user_mapping_index[user_id]
        e_u = model.users_emb.weight[user]
        scores = model.items_emb.weight @ e_u

        values, indices = t.topk(scores, k=len(user_pos_items[user]) + num_recs)

        articles = [
            index.cpu().item() for index in indices if index in user_pos_items[user]
        ][:num_recs]
        article_ids = [
            list(article_mapping_index.keys())[
                list(article_mapping_index.values()).index(article)
            ]
            for article in articles
        ]
        titles = [article_mapping_id[str(id)] for id in article_ids]

        print(f"Here are some articles that user {user_id} rated highly")
        for i in range(num_recs):
            print(f"title: {titles[i]}")

    # make_predictions(1, 10)


if __name__ == "__main__":
    train(lightgcn_config)
