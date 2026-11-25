export const reconcileViewTemplate = `
  <div class="panel" style="border-style:solid">
    <h3>对账口径（当日锁死）</h3>
    <p class="muted" style="margin:0.2rem 0">齐套不得跳过帽值比对；影子快照草稿不计正式封批，帽值不符草稿一律判不齐。</p>
  </div>
  <div class="grid-2">
    <div class="panel">
      <h3>许可对账</h3>
      <div class="actions"><button class="secondary" @click="loadReconcile">刷新全部</button></div>
      <table>
        <thead><tr><th>许可</th><th>对齐</th><th>证明</th><th>正式封批</th><th>影子草稿/作废</th></tr></thead>
        <tbody>
          <tr v-for="r in reconAllItems" :key="r.permit_code">
            <td>{{ r.permit_code }}</td>
            <td :class="r.balanced?'pass':'fail'">{{ r.balanced ? "齐" : "不齐" }}</td>
            <td :class="r.proof_ready?'pass':'warn'">{{ r.proof_ready ? "可证" : "未齐" }}</td>
            <td>{{ r.seal_count || 0 }}</td>
            <td>{{ r.shadow_draft_count || 0 }} / <span :class="r.void_draft_count?'fail':'muted'">{{ r.void_draft_count || 0 }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel">
      <h3>单许可 / 采样证明</h3>
      <label>许可号</label><input v-model="reconCode"/>
      <div class="actions"><button @click="loadReconcileOne">对账</button></div>
      <div v-if="reconOne" style="font-size:0.85rem">
        <p>许可帽：COD={{ reconOne.caps.cod }} 氨氮={{ reconOne.caps.nh3n }} 总磷={{ reconOne.caps.tp }}
          ｜ 齐套：<span :class="reconOne.balanced?'pass':'fail'">{{ reconOne.balanced ? "齐" : "不齐" }}</span></p>
        <table>
          <thead><tr><th>采样</th><th>帽值比对</th><th>不符项</th></tr></thead>
          <tbody>
            <tr v-for="s in reconOne.samples" :key="s.sample_code">
              <td>{{ s.sample_code }}</td>
              <td :class="s.cap_passed?'pass':'fail'">{{ s.cap_passed ? "帽内" : "帽值不符" }}</td>
              <td>{{ (s.cap_mismatches || []).join("、") || "—" }}</td>
            </tr>
          </tbody>
        </table>
        <details>
          <summary>逐指标帽值明细</summary>
          <pre style="white-space:pre-wrap;font-size:0.78rem">{{ JSON.stringify(reconOne.samples.map(s=>({sample:s.sample_code, cap_checks:s.cap_checks})), null, 2) }}</pre>
        </details>
      </div>
      <label>采样号证明</label><input v-model="proofCode"/>
      <div class="actions"><button class="secondary" @click="loadProof">证明</button></div>
      <pre v-if="proofOne" style="white-space:pre-wrap;font-size:0.82rem">{{ JSON.stringify(proofOne, null, 2) }}</pre>
    </div>
  </div>`;
