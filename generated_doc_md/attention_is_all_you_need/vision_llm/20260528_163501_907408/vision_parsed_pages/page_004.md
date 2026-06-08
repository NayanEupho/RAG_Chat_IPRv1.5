Scaled Dot-Product Attention $\quad$ Multi-Head Attention

[Visual: diagram | page 4]
Title: [none]
Visible text: SoftMax, Mask (opt.), Scale, MatMul, Q, K, V, Linear, Concat, Scaled Dot-Product Attention, h, Linear, Linear, Linear, V, K, Q
Axes/units: [not applicable]
Legend: [none]
Data/trend: [not applicable]
Relationships: Left diagram shows a vertical flow from inputs Q, K, V through MatMul, Scale, Mask (opt.), SoftMax, and a final MatMul. Right diagram shows three parallel paths of Linear layers feeding into a Scaled Dot-Product Attention block, then into a Concat block, and finally a Linear layer.
Short description: Two architectural diagrams illustrating the Scaled Dot-Product Attention mechanism and the Multi-Head Attention mechanism.
Unclear: [none]
[/Visual]

Figure 2: (left) Scaled Dot-Product Attention. (right) Multi-Head Attention consists of several attention layers running in parallel.

of the values, where the weight assigned to each value is computed by a compatibility function of the query with the corresponding key.

### 3.2.1 Scaled Dot-Product Attention

We call our particular attention "Scaled Dot-Product Attention" (Figure 2). The input consists of queries and keys of dimension $d_k$, and values of dimension $d_v$. We compute the dot products of the query with all keys, divide each by $\sqrt{d_k}$, and apply a softmax function to obtain the weights on the values.

In practice, we compute the attention function on a set of queries simultaneously, packed together into a matrix $Q$. The keys and values are also packed together into matrices $K$ and $V$. We compute the matrix of outputs as:

$$\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V \quad (1)$$

The two most commonly used attention functions are additive attention [2], and dot-product (multiplicative) attention. Dot-product attention is identical to our algorithm, except for the scaling factor of $\frac{1}{\sqrt{d_k}}$. Additive attention computes the compatibility function using a feed-forward network with a single hidden layer. While the two are similar in theoretical complexity, dot-product attention is much faster and more space-efficient in practice, since it can be implemented using highly optimized matrix multiplication code.

While for small values of $d_k$ the two mechanisms perform similarly, additive attention outperforms dot product attention without scaling for larger values of $d_k$ [3]. We suspect that for large values of $d_k$, the dot products grow large in magnitude, pushing the softmax function into regions where its gradients are extremely small gradients $\nabla$. To counteract this effect, we scale the dot products by $\frac{1}{\sqrt{d_k}}$.

### 3.2.2 Multi-Head Attention

Instead of performing a single attention function with dimension $d_{\text{model}}$-dimensional keys, values and queries, we found it beneficial to linearly project the queries, keys and values $h$ times with different, learned linear projections to $d_k$, $d_k$ and $d_v$ dimensions, respectively. On each of these projected tensors versions of queries, keys and values we then perform the attention function in parallel, yielding $d_v$-dimensional

---
$^4$To illustrate why the dot products get large, assume that the components of $q$ and $k$ are independent random variables with mean 0 and variance 1. Then their dot product, $q \cdot k = \sum_{i=1}^{d_k} q_i k_i$, has mean 0 and variance $d_k$.

4