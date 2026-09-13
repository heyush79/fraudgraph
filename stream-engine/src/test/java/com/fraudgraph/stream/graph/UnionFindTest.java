package com.fraudgraph.stream.graph;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class UnionFindTest {
    @Test
    void unionsMergeComponentsAndSizesAddUp() {
        UnionFind uf = new UnionFind();
        uf.union("a", "b");
        uf.union("c", "d");
        assertThat(uf.componentSize("a")).isEqualTo(2);
        assertThat(uf.find("a")).isEqualTo(uf.find("b")).isNotEqualTo(uf.find("c"));
        uf.union("b", "c");
        assertThat(uf.componentSize("d")).isEqualTo(4);
        uf.union("a", "d"); // already joined: no-op
        assertThat(uf.componentSize("a")).isEqualTo(4);
        assertThat(uf.nodeCount()).isEqualTo(4);
    }

    @Test
    void unknownNodeIsASingletonWithoutInsertion() {
        UnionFind uf = new UnionFind();
        assertThat(uf.componentSizeIfKnown("ghost")).isEqualTo(1);
        assertThat(uf.nodeCount()).isEqualTo(0);
        assertThat(uf.componentSize("solo")).isEqualTo(1);
        assertThat(uf.nodeCount()).isEqualTo(1);
    }

    @Test
    void longChainStaysCorrect() {
        UnionFind uf = new UnionFind();
        for (int i = 0; i < 1000; i++) uf.union("n" + i, "n" + (i + 1));
        assertThat(uf.componentSize("n0")).isEqualTo(1001);
        assertThat(uf.find("n0")).isEqualTo(uf.find("n1000"));
    }
}
