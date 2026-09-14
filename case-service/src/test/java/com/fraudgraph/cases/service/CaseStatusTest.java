package com.fraudgraph.cases.service;

import com.fraudgraph.cases.model.CaseStatus;
import com.fraudgraph.cases.model.Verdict;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class CaseStatusTest {
    @Test
    void onlyFlaggedVerdictsBecomeCases() {
        assertThat(Verdict.ALLOW.createsCase()).isFalse();
        assertThat(Verdict.REVIEW.createsCase()).isTrue();
        assertThat(Verdict.BLOCK.createsCase()).isTrue();
    }

    @Test
    void closedCasesAreTerminal() {
        assertThat(CaseStatus.CLOSED_FRAUD.isClosed()).isTrue();
        assertThat(CaseStatus.CLOSED_FP.isClosed()).isTrue();
        assertThat(CaseStatus.CLOSED_FRAUD.canMoveTo(CaseStatus.OPEN)).isFalse();
        assertThat(CaseStatus.CLOSED_FP.canMoveTo(CaseStatus.INVESTIGATING)).isFalse();
    }

    @Test
    void openCasesMoveFreelyButNotToThemselves() {
        assertThat(CaseStatus.OPEN.canMoveTo(CaseStatus.INVESTIGATING)).isTrue();
        assertThat(CaseStatus.OPEN.canMoveTo(CaseStatus.CLOSED_FP)).isTrue();
        assertThat(CaseStatus.INVESTIGATING.canMoveTo(CaseStatus.REPORTED)).isTrue();
        assertThat(CaseStatus.OPEN.canMoveTo(CaseStatus.OPEN)).isFalse();
        assertThat(CaseStatus.OPEN.canMoveTo(null)).isFalse();
    }
}
