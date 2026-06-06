# AUDIT EXHAUSTIF Sierra DMP vs Databento+Python — 20260605 NQ

**Sierra DMP** : 1378 bars (04/06 22:01 -> 05/06 20:58 UTC, 23h)
**Databento+Python** : 1260 bars (05/06 00:00 -> 20:59 UTC, 21h)

Legende :
- ✅ : feature present, stable
- ⚠️ : present mais fragile / null eleve
- ❌ : absent
- 🔄 : nom different mais equivalent fonctionnel

## OHLCV + Base

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `price` | fire=100.0% null=0.0% range=[28796.25..30419.25] med=30147.0 | ✅ Stable |
| `atr` | fire=100.0% null=0.0% range=[438.25..558.07] med=467.29 | ✅ Stable |
| `atr_14m` | fire=100.0% null=0.0% range=[20.14..165.71] med=50.14 | ✅ Stable |
| `session` | fire=60.8% null=0.0% range=[0.0..2.0] med=1.0 | ✅ OK |
| `session_id` | null=0.0%, vals={'Asia': 540, 'US': 478, 'London': 360} | ✅ Varies |
| `ts` | fire=100.0% null=0.0% range=[1780610460000.0..1780693080000.0] med=1780651800000.0 | ✅ Stable |
| `bar_high` | fire=100.0% null=0.0% range=[28812.0..30422.0] med=30152.75 | ✅ Stable |
| `bar_low` | fire=100.0% null=0.0% range=[28781.25..30405.75] med=30141.5 | ✅ Stable |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `open` | fire=100.0% null=0.0% range=[28796.5..30262.25] med=30135.0 | ✅ Stable |
| `high` | fire=100.0% null=0.0% range=[28812.0..30264.0] med=30140.75 | ✅ Stable |
| `low` | fire=100.0% null=0.0% range=[28781.25..30240.25] med=30129.0 | ✅ Stable |
| `close` | fire=100.0% null=0.0% range=[28796.25..30251.5] med=30134.75 | ✅ Stable |
| `volume` | fire=100.0% null=0.0% range=[20.0..16723.0] med=267.0 | ✅ Stable |
| `atr` | fire=100.0% null=0.0% range=[21.143..168.357] med=54.286 | ✅ Stable |
| `atr_14m` | fire=100.0% null=0.0% range=[5.286..42.089] med=13.571 | ✅ Stable |
| `atr_14m_pct` | fire=100.0% null=0.0% range=[0.018..0.146] med=0.045 | ✅ Stable |
| `session` | fire=66.7% null=0.0% range=[0.0..3.0] med=1.0 | ✅ OK |
| `session_id` | fire=66.7% null=0.0% range=[0.0..3.0] med=1.0 | ✅ OK |
| `ts` | fire=100.0% null=0.0% range=[1780617600000.0..1780693140000.0] med=1780655400000.0 | ✅ Stable |
| `bar_high` | fire=100.0% null=0.0% range=[28812.0..30264.0] med=30140.75 | ✅ Stable |
| `bar_low` | fire=100.0% null=0.0% range=[28781.25..30240.25] med=30129.0 | ✅ Stable |

## VWAP D/W/M + SD bands

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `dist_vwap_d` | fire=100.0% null=0.0% range=[-250.773..2568.82] med=981.094 | ✅ Stable |
| `dist_vwap_d_atr` | fire=100.0% null=0.0% range=[-0.485..4.984] med=2.098 | ✅ Stable |
| `dist_vwap_d_sd1u` | fire=100.0% null=0.0% range=[-120.273..3947.625] med=1623.461 | ✅ Stable |
| `dist_vwap_d_sd1d` | fire=99.9% null=0.0% range=[-381.273..1190.016] med=361.641 | ✅ Stable |
| `dist_vwap_d_sd2u` | fire=100.0% null=0.0% range=[2.828..5326.43] med=2269.008 | ✅ Stable |
| `dist_vwap_d_sd2d` | fire=100.0% null=0.0% range=[-1194.766..551.898] med=-314.391 | ✅ Stable |
| `dist_vwap_d_sd3u` | fire=100.0% null=0.0% range=[6.656..6705.234] med=2932.539 | ✅ Stable |
| `dist_vwap_d_sd3d` | fire=100.0% null=0.0% range=[-2307.359..155.797] med=-969.664 | ✅ Stable |
| `dist_vwap_w` | fire=100.0% null=0.0% range=[428.938..5838.289] med=1471.32 | ✅ Stable |
| `dist_vwap_w_atr` | fire=100.0% null=0.0% range=[0.979..5.0] med=3.152 | ✅ Stable |
| `dist_vwap_m` | fire=100.0% null=0.0% range=[428.938..5838.289] med=1471.32 | ✅ Stable |
| `dist_vwap_m_atr` | fire=100.0% null=0.0% range=[0.979..5.0] med=3.152 | ✅ Stable |
| `vwap_d_side` | fire=100.0% null=0.0% range=[-1.0..1.0] med=-1.0 | ✅ Stable |
| `vwap_w_side` | fire=100.0% null=0.0% range=[-1.0..-1.0] med=-1.0 | ✅ Stable |
| `vwap_m_side` | fire=100.0% null=0.0% range=[-1.0..-1.0] med=-1.0 | ✅ Stable |
| `vwap_slope_10` | fire=100.0% null=0.0% range=[-214.242..5.171] med=-2.461 | ✅ Stable |
| `vwap_slope_30` | fire=100.0% null=0.0% range=[-75.194..-0.937] med=-2.956 | ✅ Stable |
| `vwap_slope_10_dir` | fire=100.0% null=0.0% range=[-1.0..1.0] med=-1.0 | ✅ Stable |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `vwap_d` | fire=100.0% null=0.0% range=[29566.547..30386.499] med=30165.226 | ✅ Stable |
| `vwap_d_sd1u` | fire=100.0% null=0.0% range=[29946.713..30505.832] med=30200.919 | ✅ Stable |
| `vwap_d_sd1d` | fire=100.0% null=0.0% range=[29186.381..30267.166] med=30125.275 | ✅ Stable |
| `vwap_d_sd2u` | fire=100.0% null=0.0% range=[30161.167..30629.497] med=30250.388 | ✅ Stable |
| `vwap_d_sd2d` | fire=100.0% null=0.0% range=[28806.215..30166.255] med=30084.899 | ✅ Stable |
| `vwap_d_sd3u` | fire=100.0% null=0.0% range=[30161.167..30757.041] med=30383.136 | ✅ Stable |
| `vwap_d_sd3d` | fire=100.0% null=0.0% range=[28426.049..30161.167] med=30004.107 | ✅ Stable |
| `dist_vwap_d_pct` | fire=100.0% null=0.0% range=[-0.293..2.689] med=0.471 | ✅ Stable |
| `dist_vwap_d_atr` | fire=100.0% null=0.0% range=[-8.844..53.594] med=6.351 | ✅ Stable |
| `dist_vwap_d_sd1u_pct` | fire=100.0% null=0.0% range=[-0.163..3.999] med=0.891 | ✅ Stable |
| `dist_vwap_d_sd2u_pct` | fire=100.0% null=0.0% range=[-0.037..5.309] med=1.31 | ✅ Stable |
| `vwap_d_cross_up` | fire=1.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `vwap_d_cross_dn` | fire=1.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `vwap_d_sd1_above` | fire=7.7% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `vwap_d_sd2_above` | fire=1.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `vwap_w` | fire=100.0% null=0.0% range=[30250.166..30525.51] med=30509.187 | ✅ Stable |
| `vwap_w_sd1u` | fire=100.0% null=0.0% range=[30665.669..30739.437] med=30666.655 | ✅ Stable |
| `vwap_w_sd1d` | fire=100.0% null=0.0% range=[29760.894..30384.456] med=30352.384 | ✅ Stable |
| `dist_vwap_w_pct` | fire=100.0% null=0.0% range=[0.855..5.057] med=1.261 | ✅ Stable |
| `dist_vwap_w_atr` | fire=100.0% null=0.0% range=[13.106..101.66] med=32.175 | ✅ Stable |
| `vwap_m` | fire=100.0% null=0.0% range=[30250.166..30525.51] med=30509.187 | ✅ Stable |
| `vwap_m_sd1u` | fire=100.0% null=0.0% range=[30665.669..30739.437] med=30666.655 | ✅ Stable |
| `dist_vwap_m_pct` | fire=100.0% null=0.0% range=[0.855..5.057] med=1.261 | ✅ Stable |
| `dist_vwap_m_atr` | fire=100.0% null=0.0% range=[13.106..101.66] med=32.175 | ✅ Stable |
| `vwap_d_side` | fire=100.0% null=0.0% range=[-1.0..1.0] med=-1.0 | ✅ Stable |
| `vwap_slope_10` | fire=100.0% null=0.0% range=[-20.887..1.228] med=-0.147 | ✅ Stable |
| `vwap_slope_10_atr` | fire=100.0% null=0.0% range=[-2.078..0.113] med=-0.013 | ✅ Stable |

## Volume Profile (current + prev + composite)

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `dist_cur_vpoc` | fire=99.9% null=0.0% range=[-250.0..3245.0] med=1535.0 | ✅ Stable |
| `dist_cur_vah` | fire=99.8% null=0.0% range=[-144.0..3639.0] med=1684.0 | ✅ Stable |
| `dist_cur_val` | fire=99.7% null=0.0% range=[-804.0..1668.0] med=522.0 | ✅ Stable |
| `dist_cur_vwap_vp` | fire=100.0% null=0.0% range=[-250.742..2568.82] med=981.102 | ✅ Stable |
| `va_position_pct` | fire=15.5% null=84.2% range=[0.0..1.0] med=0.071 | ❌ Trop null |
| `inside_cur_va` | fire=15.8% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `range_pos` | fire=16.7% null=0.0% range=[0.0..100.0] med=0.0 | ⚠️ Sparse |
| `range_size_ticks` | fire=100.0% null=0.0% range=[40.0..3468.0] med=1398.0 | ✅ Stable |
| `vah_touches_20b` | fire=4.3% null=0.0% range=[0.0..5.0] med=0.0 | ⚠️ Rare |
| `val_touches_20b` | fire=19.4% null=0.0% range=[0.0..7.0] med=0.0 | ⚠️ Sparse |
| `bars_in_va` | fire=15.8% null=0.0% range=[0.0..43.0] med=0.0 | ⚠️ Sparse |
| `dist_prev_vpoc` | fire=99.9% null=0.0% range=[-477.0..4215.0] med=613.0 | ✅ Stable |
| `dist_prev_vah` | fire=100.0% null=0.0% range=[270.0..6416.0] med=1360.0 | ✅ Stable |
| `dist_prev_val` | fire=100.0% null=0.0% range=[-1012.0..3065.0] med=78.0 | ✅ Stable |
| `dist_prev_vwap` | fire=100.0% null=0.0% range=[-14.859..4895.281] med=1075.141 | ✅ Stable |
| `inside_prev_va` | fire=44.3% null=0.0% range=[0.0..1.0] med=0.0 | ✅ OK |
| `open_in_prev_va` | fire=80.6% null=0.0% range=[0.0..1.0] med=1.0 | ✅ OK |
| `dist_comp_20d_vpoc` | fire=100.0% null=0.0% range=[-91677.0..-85185.0] med=-90587.0 | ✅ Stable |
| `dist_comp_20d_vah` | fire=100.0% null=0.0% range=[-91377.0..-84845.0] med=-90260.0 | ✅ Stable |
| `dist_comp_20d_val` | fire=100.0% null=0.0% range=[-91625.797..-85000.281] med=-90436.797 | ✅ Stable |
| `dist_comp_20d_vwap` | fire=100.0% null=0.0% range=[-91154.203..-84561.719] med=-89989.719 | ✅ Stable |
| `dist_comp_50d_vpoc` | ABSENT | ❌ |
| `inside_comp_20d_va` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `inside_comp_50d_va` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `comp_vpoc_align_20_50` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `cur_vpoc` | fire=100.0% null=0.0% range=[29150.0..30350.0] med=30200.0 | ✅ Stable |
| `cur_vah` | fire=100.0% null=0.0% range=[29878.5..30391.75] med=30236.0 | ✅ Stable |
| `cur_val` | fire=100.0% null=0.0% range=[28972.25..30293.25] med=30107.0 | ✅ Stable |
| `dist_cur_vpoc_pct` | fire=99.6% null=0.0% range=[-0.305..1.644] med=0.175 | ✅ Stable |
| `dist_cur_vah_pct` | fire=100.0% null=0.0% range=[-0.069..3.919] med=0.444 | ✅ Stable |
| `dist_cur_val_pct` | fire=99.9% null=0.0% range=[-0.682..1.211] med=-0.094 | ✅ Stable |
| `dist_cur_vpoc_atr` | fire=99.6% null=0.0% range=[-11.598..23.892] med=4.081 | ✅ Stable |
| `dist_cur_vah_atr` | fire=100.0% null=0.0% range=[-1.36..76.788] med=9.925 | ✅ Stable |
| `dist_cur_val_atr` | fire=99.9% null=0.0% range=[-19.309..11.875] med=-1.764 | ✅ Stable |
| `inside_value_area` | fire=66.7% null=0.0% range=[0.0..1.0] med=1.0 | ✅ OK |
| `inside_cur_va` | fire=66.7% null=0.0% range=[0.0..1.0] med=1.0 | ✅ OK |
| `va_position_pct` | fire=66.8% null=0.0% range=[0.0..1.0] med=0.125 | ✅ OK |
| `poc_position` | fire=66.8% null=0.0% range=[0.0..1.0] med=0.125 | ✅ OK |
| `prev_vpoc` | fire=100.0% null=0.0% range=[30300.0..30300.0] med=30300.0 | ✅ Stable |
| `prev_vah` | fire=100.0% null=0.0% range=[30473.75..30473.75] med=30473.75 | ✅ Stable |
| `prev_val` | fire=100.0% null=0.0% range=[30166.25..30166.25] med=30166.25 | ✅ Stable |
| `dist_prev_vpoc_pct` | fire=100.0% null=0.0% range=[0.16..5.222] med=0.549 | ✅ Stable |
| `dist_prev_vah_pct` | fire=100.0% null=0.0% range=[0.735..5.825] med=1.126 | ✅ Stable |
| `dist_prev_val_pct` | fire=100.0% null=0.0% range=[-0.282..4.758] med=0.105 | ✅ Stable |
| `dist_prev_vpoc_atr` | fire=100.0% null=0.0% range=[3.14..105.0] med=14.249 | ✅ Stable |
| `dist_prev_vah_atr` | fire=100.0% null=0.0% range=[11.385..117.254] med=29.777 | ✅ Stable |
| `dist_prev_val_atr` | fire=100.0% null=0.0% range=[-9.639..95.567] med=2.515 | ✅ Stable |
| `poc_migration_dir` | fire=100.0% null=0.0% range=[-1.0..1.0] med=-1.0 | ✅ Stable |
| `cur_va_n_buckets` | fire=100.0% null=0.0% range=[744.0..6535.0] med=1478.0 | ✅ Stable |
| `cur_va_total_vol` | fire=100.0% null=0.0% range=[16467.0..997788.0] med=126967.0 | ✅ Stable |
| `ctx_va_width` | fire=100.0% null=0.0% range=[103.5..1487.0] med=177.5 | ✅ Stable |
| `ctx_va_developing_10` | fire=99.6% null=0.0% range=[-422.25..364.25] med=-1.25 | ✅ Stable |

## POC MIGRATION (Jackson note: a CREER)

### Sierra : RIEN

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `poc_migration_dir` | fire=100.0% null=0.0% range=[-1.0..1.0] med=-1.0 | ✅ Stable |
| `ctx_poc_migration_10` | fire=77.7% null=0.0% range=[-0.043..0.082] med=0.0 | ✅ OK |

## Niveaux veille + Overnight + Cash

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `dist_open_cash` | fire=99.9% null=0.0% range=[-308.0..6731.0] med=1224.0 | ✅ Stable |
| `dist_open_830` | fire=100.0% null=0.0% range=[-185.0..5680.0] med=779.0 | ✅ Stable |
| `dist_ovn_high` | ABSENT | ❌ |
| `dist_ovn_low` | ABSENT | ❌ |
| `ovn_range_ticks` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `open_gap_ticks` | fire=100.0% null=0.0% range=[-2516.0..1119.0] med=-716.0 | ✅ Stable |
| `open_position` | fire=19.4% null=0.0% range=[-2.0..2.0] med=0.0 | ⚠️ Sparse |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `cur_pdh` | fire=100.0% null=0.0% range=[30422.0..30422.0] med=30422.0 | ✅ Stable |
| `cur_pdl` | fire=100.0% null=0.0% range=[28781.25..30233.75] med=30052.25 | ✅ Stable |
| `pdh` | fire=100.0% null=0.0% range=[30603.25..30603.25] med=30603.25 | ✅ Stable |
| `pdl` | fire=100.0% null=0.0% range=[30151.0..30151.0] med=30151.0 | ✅ Stable |
| `dist_pdh_pct` | fire=100.0% null=0.0% range=[1.163..6.275] med=1.556 | ✅ Stable |
| `dist_pdl_pct` | fire=99.8% null=0.0% range=[-0.332..4.705] med=0.055 | ✅ Stable |
| `dist_pdh_atr` | fire=100.0% null=0.0% range=[16.026..126.388] med=40.316 | ✅ Stable |
| `dist_pdl_atr` | fire=99.8% null=0.0% range=[-11.567..94.491] med=1.336 | ✅ Stable |
| `ovn_high` | fire=35.7% null=64.3% range=[30422.0..30422.0] med=30422.0 | ❌ Trop null |
| `ovn_low` | fire=35.7% null=64.3% range=[30013.0..30013.0] med=30013.0 | ❌ Trop null |
| `ovn_range_ticks` | fire=35.7% null=64.3% range=[1636.0..1636.0] med=1636.0 | ❌ Trop null |
| `dist_ovn_high_pct` | fire=35.7% null=64.3% range=[-5.646..-1.079] med=-3.322 | ❌ Trop null |
| `dist_ovn_low_pct` | fire=35.7% null=64.3% range=[-4.225..0.28] med=-1.933 | ❌ Trop null |
| `ovn_broken_up` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `ovn_broken_dn` | fire=35.4% null=0.0% range=[0.0..1.0] med=0.0 | ✅ OK |
| `cash_high` | fire=31.0% null=69.0% range=[30059.5..30100.5] med=30100.5 | ❌ Trop null |
| `cash_low` | fire=31.0% null=69.0% range=[28974.25..29998.75] med=29418.0 | ❌ Trop null |
| `dist_cash_high_pct` | fire=31.0% null=69.0% range=[0.005..3.838] med=2.089 | ❌ Trop null |
| `dist_cash_low_pct` | fire=30.9% null=69.0% range=[-0.691..0.0] med=-0.145 | ❌ Trop null |
| `is_new_cash_high` | fire=0.2% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `is_new_cash_low` | fire=7.8% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `open_cash` | fire=54.8% null=45.2% range=[30020.25..30242.75] med=30020.25 | ✅ OK |
| `open_830_et` | fire=59.5% null=40.5% range=[30116.0..30249.0] med=30116.0 | ✅ OK |
| `open_930_et` | fire=54.8% null=45.2% range=[30035.75..30268.25] med=30035.75 | ✅ OK |
| `dist_open_830_pct` | fire=59.5% null=40.5% range=[-4.583..0.047] med=-0.982 | ✅ OK |
| `above_open_830` | fire=0.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `dist_open_930_pct` | fire=54.8% null=45.2% range=[-4.304..0.204] med=-0.943 | ✅ OK |
| `above_open_930` | fire=0.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |

## Session high/low + IB

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `dist_sess_high` | fire=100.0% null=0.0% range=[736.0..7228.0] med=1826.0 | ✅ Stable |
| `dist_sess_low` | fire=99.8% null=0.0% range=[-797.0..2331.0] med=-282.0 | ✅ Stable |
| `sess_range_ticks` | fire=100.0% null=0.0% range=[843.0..4897.0] med=2204.0 | ✅ Stable |
| `sess_range_atr` | fire=100.0% null=0.0% range=[1.924..9.502] med=4.717 | ✅ Stable |
| `dist_ib_high` | fire=28.3% null=71.7% range=[6.0..4450.0] med=2464.0 | ❌ Trop null |
| `dist_ib_low` | fire=28.3% null=71.7% range=[-728.0..3080.0] med=1094.0 | ❌ Trop null |
| `ib_range_ticks` | fire=28.3% null=0.0% range=[0.0..1370.0] med=0.0 | ⚠️ Sparse |
| `ib_range_atr` | fire=28.3% null=71.7% range=[0.516..2.806] med=2.658 | ❌ Trop null |
| `ib_is_narrow` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `ib_is_wide` | fire=28.2% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `ib_position_pct` | fire=3.0% null=97.0% range=[0.0007..0.494] med=0.235 | ❌ Trop null |
| `ib_broken_up` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `ib_broken_down` | fire=20.8% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `ib_complete` | fire=23.9% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `sess_high` | fire=100.0% null=0.0% range=[30422.0..30422.0] med=30422.0 | ✅ Stable |
| `sess_low` | fire=100.0% null=0.0% range=[28781.25..30233.75] med=30052.25 | ✅ Stable |
| `dist_sess_high_pct` | fire=100.0% null=0.0% range=[0.564..5.646] med=0.954 | ✅ Stable |
| `dist_sess_low_pct` | fire=99.8% null=0.0% range=[-0.691..0.0] med=-0.296 | ✅ Stable |
| `dist_sess_high_atr` | fire=100.0% null=0.0% range=[8.935..113.605] med=25.055 | ✅ Stable |
| `dist_sess_low_atr` | fire=99.8% null=0.0% range=[-28.215..0.0] med=-5.171 | ✅ Stable |
| `sess_range_atr` | fire=100.0% null=0.0% range=[2.964..28.798] med=8.956 | ✅ Stable |
| `is_new_sess_high` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `is_new_sess_low` | fire=12.5% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `ib_high` | fire=50.0% null=50.0% range=[30100.5..30364.5] med=30100.5 | ✅ OK |
| `ib_low` | fire=50.0% null=50.0% range=[29758.0..30151.0] med=29758.0 | ✅ OK |
| `ib_range` | fire=50.0% null=50.0% range=[213.5..342.5] med=342.5 | ✅ OK |
| `ib_range_ticks` | fire=50.0% null=50.0% range=[854.0..1370.0] med=1370.0 | ✅ OK |
| `ib_range_atr` | fire=50.0% null=50.0% range=[8.137..26.989] med=14.731 | ✅ OK |
| `dist_ib_high_pct` | fire=50.0% null=50.0% range=[0.402..4.529] med=1.481 | ✅ OK |
| `dist_ib_low_pct` | fire=49.9% null=50.0% range=[-0.566..3.34] med=0.326 | ✅ OK |
| `dist_ib_high_atr` | fire=50.0% null=50.0% range=[5.58..90.929] med=20.26 | ✅ OK |
| `dist_ib_low_atr` | fire=49.9% null=50.0% range=[-11.567..66.773] med=4.162 | ✅ OK |
| `ib_position_pct` | fire=49.9% null=50.0% range=[-2.808..0.494] med=-0.291 | ✅ OK |
| `ib_broken_up` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `ib_broken_dn` | fire=32.7% null=0.0% range=[0.0..1.0] med=0.0 | ✅ OK |
| `ib_broken_down` | fire=32.7% null=0.0% range=[0.0..1.0] med=0.0 | ✅ OK |
| `ib_complete` | fire=50.0% null=0.0% range=[0.0..1.0] med=1.0 | ✅ OK |
| `is_ib_window` | fire=4.8% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `ctx_ib_extension_ratio` | fire=50.0% null=50.0% range=[0.253..1.904] med=0.646 | ✅ OK |
| `ctx_ib_position_velocity` | fire=49.4% null=50.4% range=[-0.477..0.353] med=-0.028 | ❌ Trop null |

## MenthorQ levels + GEX

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `dist_mq_call` | fire=100.0% null=0.0% range=[843.0..7615.0] med=2149.0 | ✅ Stable |
| `dist_mq_put` | fire=100.0% null=0.0% range=[-1406.0..4415.0] med=951.0 | ✅ Stable |
| `dist_mq_hvl` | fire=72.9% null=27.1% range=[354.0..6175.0] med=1007.0 | ✅ OK |
| `dist_mq_call_0dte` | fire=100.0% null=0.0% range=[843.0..7615.0] med=2149.0 | ✅ Stable |
| `dist_mq_put_0dte` | fire=100.0% null=0.0% range=[963.0..6935.0] med=1783.0 | ✅ Stable |
| `dist_mq_hvl_0dte` | ABSENT | ❌ |
| `dist_gex_nearest_up` | fire=100.0% null=0.0% range=[10.0..4015.0] med=656.0 | ✅ Stable |
| `dist_gex_nearest_dn` | fire=73.8% null=26.2% range=[-1677.0..-5.0] med=-726.0 | ✅ OK |
| `gex_cluster_count` | fire=0.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `dist_blind_nearest_up` | ABSENT | ❌ |
| `dist_blind_nearest_dn` | ABSENT | ❌ |
| `next_wall_dist_ticks` | fire=100.0% null=0.0% range=[5.0..4015.0] med=484.0 | ✅ Stable |
| `next_wall_is_call` | fire=68.7% null=0.0% range=[0.0..1.0] med=1.0 | ✅ OK |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `mq_call` | fire=100.0% null=0.0% range=[30630.0..30700.0] med=30700.0 | ✅ Stable |
| `mq_put` | fire=100.0% null=0.0% range=[29900.0..30660.0] med=29900.0 | ✅ Stable |
| `mq_hvl` | fire=79.8% null=20.2% range=[30340.0..30340.0] med=30340.0 | ✅ OK |
| `mq_call_0dte` | ABSENT | ❌ |
| `mq_put_0dte` | fire=79.8% null=20.2% range=[30530.0..30530.0] med=30530.0 | ✅ OK |
| `mq_hvl_0dte` | ABSENT | ❌ |
| `mq_1d_min` | fire=100.0% null=0.0% range=[30121.199..30240.789] med=30121.199 | ✅ Stable |
| `mq_1d_max` | fire=100.0% null=0.0% range=[30855.301..31025.711] med=30855.301 | ✅ Stable |
| `mq_gex` | null=0.0%, vals={'<complex_type>': 1260} | ⚠️ FIGE |
| `mq_blind` | null=0.0%, vals={'<complex_type>': 1260} | ⚠️ FIGE |
| `dist_mq_call_pct` | fire=100.0% null=0.0% range=[1.28..6.611] med=1.845 | ✅ Stable |
| `dist_mq_put_pct` | fire=100.0% null=0.0% range=[-1.162..3.833] med=0.258 | ✅ Stable |
| `dist_mq_hvl_pct` | fire=79.8% null=20.2% range=[0.293..5.361] med=0.84 | ✅ OK |
| `dist_mq_put_0dte_pct` | fire=79.8% null=20.2% range=[0.921..6.021] med=1.472 | ✅ OK |
| `dist_gex_nearest_up_pct` | fire=100.0% null=0.0% range=[0.008..3.486] med=0.56 | ✅ Stable |
| `dist_gex_nearest_dn_pct` | fire=71.3% null=28.7% range=[-0.803..-0.004] med=-0.577 | ✅ OK |
| `dist_mq_call_atr` | fire=100.0% null=0.0% range=[18.395..133.212] med=46.504 | ✅ Stable |
| `dist_mq_put_atr` | fire=100.0% null=0.0% range=[-56.851..76.788] med=2.447 | ✅ Stable |
| `dist_mq_hvl_atr` | fire=79.8% null=20.2% range=[5.053..107.821] med=19.161 | ✅ OK |
| `next_wall_dist_ticks` | fire=100.0% null=0.0% range=[2.0..4015.0] med=456.0 | ✅ Stable |
| `bool_gex_flip_zone` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `ctx_mq_put_call_ratio` | fire=100.0% null=0.0% range=[0.000625..1.078] med=0.509 | ✅ Stable |

## VIX + macro

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `vix_level` | fire=100.0% null=0.0% range=[15.4..21.51] med=15.69 | ✅ Stable |
| `dist_vix_hvl` | fire=100.0% null=0.0% range=[-0.01..6.1] med=5.81 | ✅ Stable |
| `vix_regime` | fire=100.0% null=0.0% range=[1.0..1.0] med=1.0 | ✅ Stable |
| `vix_above_hvl` | fire=3.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `dist_vix_call` | fire=100.0% null=0.0% range=[3.49..9.6] med=9.32 | ✅ Stable |
| `dist_vix_put` | fire=100.0% null=0.0% range=[-6.51..0.6] med=-0.68 | ✅ Stable |
| `dist_vix_call_0dte` | fire=99.9% null=0.1% range=[-5.51..0.6] med=0.31 | ✅ Stable |
| `dist_vix_put_0dte` | fire=100.0% null=0.0% range=[-6.51..-0.4] med=-0.68 | ✅ Stable |
| `dist_vix_hvl_0dte` | fire=100.0% null=0.0% range=[-0.01..6.1] med=5.81 | ✅ Stable |
| `vix_above_hvl_0dte` | fire=3.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `dist_vix_gex_nearest_up` | fire=95.6% null=4.4% range=[0.01..1.1] med=0.13 | ✅ Stable |
| `dist_vix_gex_nearest_dn` | fire=59.9% null=40.1% range=[-1.0..-0.01] med=-0.24 | ✅ OK |

### Databento : RIEN

## Delta / Aggressor

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `delta_bar` | fire=99.1% null=0.0% range=[-799.0..641.0] med=-2.0 | ✅ Stable |
| `delta_bar_vol_norm` | fire=99.1% null=0.0% range=[-0.64..0.673] med=-0.007 | ✅ Stable |
| `ask_bid_imbalance` | fire=99.1% null=0.0% range=[-0.64..0.673] med=-0.007 | ✅ Stable |
| `delta_day` | fire=100.0% null=0.0% range=[-10479.0..1904.0] med=-153.0 | ✅ Stable |
| `delta_day_dir` | fire=100.0% null=0.0% range=[-1.0..1.0] med=-1.0 | ✅ Stable |
| `ask_pct` | fire=100.0% null=0.0% range=[0.18..0.837] med=0.496 | ✅ Stable |
| `bid_pct` | fire=100.0% null=0.0% range=[0.163..0.82] med=0.504 | ✅ Stable |
| `avg_trade_size` | fire=100.0% null=0.0% range=[1.174..73.364] med=5.333 | ✅ Stable |
| `avg_bid_size` | fire=100.0% null=0.0% range=[1.167..36.819] med=3.4 | ✅ Stable |
| `avg_ask_size` | fire=100.0% null=0.0% range=[1.0..37.031] med=3.328 | ✅ Stable |
| `large_trader_ratio` | fire=100.0% null=0.0% range=[0.407..3.975] med=0.995 | ✅ Stable |
| `vol_per_sec` | fire=100.0% null=0.0% range=[0.357..278.783] med=3.915 | ✅ Stable |
| `bar_duration_sec` | fire=100.0% null=0.0% range=[45.0..60.0] med=60.0 | ✅ Stable |
| `finish_strength` | fire=90.1% null=0.0% range=[-197.0..316.0] med=0.0 | ✅ Stable |
| `finish_delta_pct` | fire=88.6% null=0.0% range=[0.0..1.0] med=1.0 | ✅ OK |
| `high_pullback_delta` | fire=96.8% null=0.0% range=[-6.0..133.0] med=1.0 | ✅ Stable |
| `low_pullback_delta` | fire=97.1% null=0.0% range=[-5.0..368.0] med=1.0 | ✅ Stable |
| `poc_bar_dist` | fire=94.6% null=0.0% range=[0.0..212.0] med=11.0 | ✅ Stable |
| `cvd_day` | fire=100.0% null=0.0% range=[-32281.0..-10784.0] med=-12841.0 | ✅ Stable |
| `cvd_day_dir` | fire=100.0% null=0.0% range=[-1.0..-1.0] med=-1.0 | ✅ Stable |
| `cvd_ohlc_range` | fire=100.0% null=0.0% range=[1985.0..12250.0] med=3157.0 | ✅ Stable |
| `diag_pos_delta` | fire=99.8% null=0.0% range=[0.0..1436.0] med=55.0 | ✅ Stable |
| `diag_neg_delta` | fire=100.0% null=0.0% range=[1.0..1425.0] med=55.0 | ✅ Stable |
| `diag_imbalance` | fire=99.0% null=0.0% range=[-1.0..0.943] med=-0.018 | ✅ Stable |
| `delta_divergence` | fire=3.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `buy_vol` | fire=100.0% null=0.0% range=[5.0..8369.0] med=119.0 | ✅ Stable |
| `sell_vol` | fire=100.0% null=0.0% range=[7.0..8358.0] med=115.0 | ✅ Stable |
| `buy_sell_ratio` | fire=100.0% null=0.0% range=[0.18..0.837] med=0.496 | ✅ Stable |
| `total_vol` | fire=100.0% null=0.0% range=[20.0..16727.0] med=232.0 | ✅ Stable |
| `delta_pct` | fire=99.1% null=0.0% range=[-0.64..0.673] med=-0.007 | ✅ Stable |
| `ticks_count` | fire=100.0% null=0.0% range=[20.0..14139.0] med=210.0 | ✅ Stable |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `delta_bar` | fire=98.9% null=0.0% range=[-641.0..799.0] med=2.0 | ✅ Stable |
| `delta_pct` | fire=98.9% null=0.0% range=[-0.642..0.63] med=0.007 | ✅ Stable |
| `delta_change` | fire=99.1% null=0.0% range=[-1104.0..868.0] med=0.0 | ✅ Stable |
| `aggressor_imbalance` | fire=98.7% null=0.0% range=[-0.556..0.615] med=0.0 | ✅ Stable |
| `diag_imbalance_ofi_proxy` | fire=98.9% null=0.0% range=[-0.642..0.63] med=0.007 | ✅ Stable |
| `max_delta_bar` | fire=98.0% null=0.0% range=[-4.0..908.0] med=25.0 | ✅ Stable |
| `min_delta_bar` | fire=97.8% null=0.0% range=[-676.0..3.0] med=-22.0 | ✅ Stable |
| `max_size_buy` | fire=100.0% null=0.0% range=[1.0..392.0] med=5.0 | ✅ Stable |
| `max_size_sell` | fire=100.0% null=0.0% range=[1.0..500.0] med=5.0 | ✅ Stable |
| `p99_trade_size` | fire=100.0% null=0.0% range=[1.74..25.25] med=4.01 | ✅ Stable |
| `delta_day` | fire=100.0% null=0.0% range=[-1032.0..20384.0] med=928.0 | ✅ Stable |
| `cvd_day` | fire=100.0% null=0.0% range=[-1032.0..20384.0] med=928.0 | ✅ Stable |
| `cvd_session` | fire=100.0% null=0.0% range=[-1775.0..20846.0] med=842.0 | ✅ Stable |
| `delta_day_dir` | fire=100.0% null=0.0% range=[-1.0..1.0] med=1.0 | ✅ Stable |
| `cvd_5d_rolling_ffd` | fire=100.0% null=0.0% range=[-608.005..3311.0] med=46.363 | ✅ Stable |
| `large_trader_max_size_proxy` | fire=100.0% null=0.0% range=[0.014..34.0] med=1.0 | ✅ Stable |
| `n_ticks_bar` | fire=100.0% null=0.0% range=[10.0..367.0] med=49.0 | ✅ Stable |
| `total_vol` | fire=100.0% null=0.0% range=[20.0..16723.0] med=267.0 | ✅ Stable |
| `finish_pct_up` | fire=96.3% null=0.0% range=[0.0..100.0] med=47.706 | ✅ Stable |
| `finish_strong_up` | fire=23.7% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `finish_strong_dn` | fire=26.2% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `finish_strength` | fire=99.0% null=0.0% range=[-100.0..100.0] med=-12.121 | ✅ Stable |
| `ctx_delta_sum_3` | fire=99.5% null=0.0% range=[-1000.0..1472.0] med=4.0 | ✅ Stable |
| `ctx_delta_sum_10` | fire=99.4% null=0.0% range=[-1306.0..3036.0] med=15.0 | ✅ Stable |
| `ctx_delta_slope_5` | fire=99.9% null=0.0% range=[-268.7..223.5] med=-0.4 | ✅ Stable |
| `ctx_cvd_recovery_rate` | fire=99.4% null=0.0% range=[-2.299..2.11] med=0.052 | ✅ Stable |
| `ctx_cvd_session` | fire=100.0% null=0.0% range=[-1775.0..20846.0] med=842.0 | ✅ Stable |

## Big orders + clusters + walls

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `dist_big_ask_nearest_up` | fire=59.7% null=3.2% range=[0.0..113.0] med=2.0 | ✅ OK |
| `dist_big_ask_nearest_dn` | fire=88.9% null=11.1% range=[-86.0..-1.0] med=-2.0 | ✅ OK |
| `dist_big_bid_nearest_up` | fire=58.8% null=3.6% range=[0.0..110.0] med=2.0 | ✅ OK |
| `dist_big_bid_nearest_dn` | fire=91.9% null=8.1% range=[-100.0..-1.0] med=-3.0 | ✅ Stable |
| `n_big_ask_t1` | fire=100.0% null=0.0% range=[10.0..20.0] med=20.0 | ✅ Stable |
| `n_big_bid_t1` | fire=100.0% null=0.0% range=[10.0..20.0] med=20.0 | ✅ Stable |
| `n_big_ask_t2` | fire=79.6% null=0.0% range=[0.0..20.0] med=3.0 | ✅ OK |
| `n_big_bid_t2` | fire=94.9% null=0.0% range=[0.0..20.0] med=4.0 | ✅ Stable |
| `n_big_ask_t3` | fire=46.3% null=0.0% range=[0.0..20.0] med=0.0 | ✅ OK |
| `n_big_bid_t3` | fire=41.3% null=0.0% range=[0.0..20.0] med=0.0 | ✅ OK |
| `n_big_ask_t4` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `n_big_bid_t4` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `big_ask_cluster_20t` | fire=84.8% null=0.0% range=[0.0..26.0] med=4.0 | ✅ OK |
| `big_bid_cluster_20t` | fire=81.7% null=0.0% range=[0.0..25.0] med=3.0 | ✅ OK |
| `big_ask_cluster_50t` | fire=94.3% null=0.0% range=[0.0..39.0] med=8.0 | ✅ Stable |
| `big_bid_cluster_50t` | fire=89.7% null=0.0% range=[0.0..31.0] med=7.0 | ✅ OK |
| `big_ask_cluster_20t_t1` | fire=84.8% null=0.0% range=[0.0..19.0] med=4.0 | ✅ OK |
| `big_bid_cluster_20t_t1` | fire=81.7% null=0.0% range=[0.0..16.0] med=3.0 | ✅ OK |
| `dist_cluster_nearest_up` | fire=60.4% null=7.3% range=[0.0..158.0] med=4.0 | ✅ OK |
| `dist_cluster_nearest_dn` | fire=87.8% null=12.2% range=[-159.0..-1.0] med=-4.0 | ✅ OK |
| `n_clusters_20t` | fire=85.1% null=0.0% range=[0.0..20.0] med=4.0 | ✅ OK |
| `n_clusters_50t` | fire=95.3% null=0.0% range=[0.0..20.0] med=9.0 | ✅ Stable |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `n_big_t1` | fire=39.6% null=0.0% range=[0.0..63.0] med=0.0 | ✅ OK |
| `n_big_buy_t1` | fire=27.3% null=0.0% range=[0.0..26.0] med=0.0 | ⚠️ Sparse |
| `n_big_sell_t1` | fire=29.0% null=0.0% range=[0.0..37.0] med=0.0 | ⚠️ Sparse |
| `n_big_t2` | fire=10.2% null=0.0% range=[0.0..5.0] med=0.0 | ⚠️ Sparse |
| `n_big_buy_t2` | fire=6.4% null=0.0% range=[0.0..4.0] med=0.0 | ⚠️ Sparse |
| `n_big_sell_t2` | fire=4.4% null=0.0% range=[0.0..3.0] med=0.0 | ⚠️ Rare |
| `n_big_t3` | fire=2.9% null=0.0% range=[0.0..2.0] med=0.0 | ⚠️ Rare |
| `n_big_buy_t3` | fire=2.1% null=0.0% range=[0.0..2.0] med=0.0 | ⚠️ Rare |
| `n_big_sell_t3` | fire=0.7% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `n_big_t4` | fire=0.2% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `n_big_buy_t4` | fire=0.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `n_big_sell_t4` | fire=0.2% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `n_big_ask_v2_t1` | fire=17.3% null=0.0% range=[0.0..85.0] med=0.0 | ⚠️ Sparse |
| `n_big_bid_v2_t1` | fire=17.8% null=0.0% range=[0.0..85.0] med=0.0 | ⚠️ Sparse |
| `n_big_ask_v2_t2` | fire=6.9% null=0.0% range=[0.0..20.0] med=0.0 | ⚠️ Sparse |
| `n_big_bid_v2_t2` | fire=4.7% null=0.0% range=[0.0..19.0] med=0.0 | ⚠️ Rare |
| `n_big_ask_v2_t3` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `n_big_bid_v2_t3` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `max_big_ask_vol_in_bar` | fire=100.0% null=0.0% range=[2.0..868.0] med=13.0 | ✅ Stable |
| `max_big_bid_vol_in_bar` | fire=100.0% null=0.0% range=[1.0..506.0] med=13.0 | ✅ Stable |
| `big_buy_dominance` | fire=87.7% null=0.0% range=[0.0..1.0] med=0.5 | ✅ OK |
| `big_sell_dominance` | fire=89.4% null=0.0% range=[0.0..1.0] med=0.5 | ✅ OK |
| `n_clusters` | fire=54.3% null=0.0% range=[0.0..195.0] med=1.0 | ✅ OK |
| `n_cluster_groups` | fire=4.0% null=0.0% range=[0.0..11.0] med=0.0 | ⚠️ Rare |
| `max_cluster_size` | fire=4.0% null=0.0% range=[0.0..21.0] med=0.0 | ⚠️ Rare |
| `max_cluster_volume` | fire=100.0% null=0.0% range=[3.0..985.0] med=22.0 | ✅ Stable |
| `max_cluster_volume_v2` | fire=4.0% null=0.0% range=[0.0..3044.0] med=0.0 | ⚠️ Rare |
| `cluster_at_high` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `cluster_at_low` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `dist_big_ask_nearest_pct` | fire=26.3% null=72.7% range=[0.0..0.143] med=0.013 | ❌ Trop null |
| `dist_big_bid_nearest_pct` | fire=28.4% null=71.0% range=[0.0..0.194] med=0.012 | ❌ Trop null |
| `dist_cluster_nearest_up_pct` | fire=40.5% null=59.5% range=[0.000828..0.058] med=0.002 | ❌ Trop null |
| `dist_cluster_nearest_dn_pct` | fire=39.8% null=60.2% range=[0.000828..0.056] med=0.002 | ❌ Trop null |

## BN (Battle Navale) Color / Long / Pressure / Absorb / Trapped

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `bn_color_up` | fire=15.5% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `bn_color_dn` | fire=19.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `bn_color_up_2` | fire=1.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `bn_color_dn_2` | fire=2.8% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `bn_absorb_ask` | fire=0.7% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `bn_absorb_bid` | fire=0.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `bn_long_up` | fire=34.9% null=0.0% range=[0.0..1.0] med=0.0 | ✅ OK |
| `bn_long_dn` | fire=36.4% null=0.0% range=[0.0..1.0] med=0.0 | ✅ OK |
| `bn_pressure_ask` | fire=11.5% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `bn_pressure_bid` | fire=12.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `bn_score_raw` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bn_score_bull` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bn_score_bear` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bn_volume_up` | fire=15.0% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `bn_volume_dn` | fire=15.5% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `bn_absorb_ask` | fire=0.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `bn_absorb_bid` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bn_absorb_ask_raw` | fire=0.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `bn_absorb_bid_raw` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bn_stack_ask` | fire=0.2% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `bn_stack_bid` | fire=0.2% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `bn_trapped_buyers_raw` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bn_trapped_sellers_raw` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bn_trapped_buyers_at_resistance` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bn_trapped_sellers_at_support` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bn_absorb_ask_at_level` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bn_absorb_bid_at_level` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `n_trapped_buyers_zones_active` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `n_trapped_sellers_zones_active` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `dist_trapped_buyers_nearest_pct` | ABSENT | ❌ |
| `dist_trapped_sellers_nearest_pct` | ABSENT | ❌ |
| `near_resistance_level` | fire=4.0% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `near_support_level` | fire=15.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |

## Bar shape + footprint

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `bar_color_up` | fire=8.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `bar_color_dn` | fire=10.0% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `bar_long_up_bar` | fire=18.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `bar_long_dn_bar` | fire=19.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `bar_long_dn_up` | fire=4.5% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `bar_long_up_dn` | fire=4.7% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `bar_edge_buy` | fire=76.0% null=0.0% range=[0.0..1.0] med=1.0 | ✅ OK |
| `bar_edge_sell` | fire=73.4% null=0.0% range=[0.0..1.0] med=1.0 | ✅ OK |
| `bar_pressure_ask` | fire=10.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `bar_pressure_bid` | fire=11.5% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `fp_edge_buy` | fire=12.2% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `fp_edge_sell` | fire=11.7% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `long_up_bar` | fire=34.5% null=0.0% range=[0.0..1.0] med=0.0 | ✅ OK |
| `long_dn_bar` | fire=36.7% null=0.0% range=[0.0..1.0] med=0.0 | ✅ OK |
| `bar_body_ticks` | fire=99.0% null=0.0% range=[-367.0..356.0] med=-5.0 | ✅ Stable |
| `bar_body_pct` | fire=99.0% null=0.0% range=[-100.0..100.0] med=-12.121 | ✅ Stable |
| `bar_upper_wick_pct` | fire=91.7% null=0.0% range=[0.0..0.119] med=0.009 | ✅ Stable |
| `bar_lower_wick_pct` | fire=92.2% null=0.0% range=[0.0..0.11] med=0.01 | ✅ Stable |
| `bar_no_trade` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |

## EXTENSION LINES (Sierra fragile, Python recalc gagne)

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `dist_ext_color_up` | fire=10.2% null=89.6% range=[-495.0..441.0] med=2.0 | ❌ Trop null |
| `dist_ext_color_dn` | fire=23.1% null=76.4% range=[-500.0..496.0] med=-144.0 | ❌ Trop null |
| `dist_ext_long_up` | fire=11.5% null=88.2% range=[-21.0..499.0] med=168.0 | ❌ Trop null |
| `dist_ext_long_dn` | fire=8.6% null=91.4% range=[-16.0..482.0] med=135.0 | ❌ Trop null |
| `dist_ext_edge_buy` | fire=81.1% null=11.8% range=[-335.0..10.0] med=-1.0 | ✅ OK |
| `dist_ext_edge_sell` | fire=81.3% null=10.2% range=[-10.0..226.0] med=0.0 | ✅ OK |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `dist_long_up_nearest_pct` | fire=86.3% null=12.8% range=[-0.359..0.0] med=-0.043 | ✅ OK |
| `dist_long_dn_nearest_pct` | fire=99.3% null=0.0% range=[-0.04..0.667] med=0.042 | ✅ Stable |
| `dist_color_up_nearest_pct` | fire=81.7% null=18.3% range=[-0.505..-0.002] med=-0.07 | ✅ OK |
| `dist_color_dn_nearest_pct` | fire=99.9% null=0.0% range=[0.0..0.567] med=0.074 | ✅ Stable |
| `dist_edge_buy_nearest_pct` | fire=99.7% null=0.0% range=[-0.506..2.741] med=1.245 | ✅ Stable |
| `dist_edge_sell_nearest_pct` | fire=99.8% null=0.0% range=[-0.689..1.638] med=1.018 | ✅ Stable |
| `n_long_up_zones_active` | fire=87.2% null=0.0% range=[0.0..13.0] med=4.0 | ✅ OK |
| `n_long_dn_zones_active` | fire=100.0% null=0.0% range=[48.0..100.0] med=59.0 | ✅ Stable |
| `n_edge_buy_active` | fire=100.0% null=0.0% range=[2.0..11.0] med=2.0 | ✅ Stable |
| `n_edge_sell_active` | fire=100.0% null=0.0% range=[7.0..19.0] med=8.0 | ✅ Stable |
| `n_color_up_cluster_within_0_2pct` | fire=72.7% null=0.0% range=[0.0..6.0] med=1.0 | ✅ OK |
| `n_color_dn_cluster_within_0_2pct` | fire=88.4% null=0.0% range=[0.0..8.0] med=2.0 | ✅ OK |
| `n_long_up_cluster_within_0_2pct` | fire=85.0% null=0.0% range=[0.0..7.0] med=2.0 | ✅ OK |
| `n_long_dn_cluster_within_0_2pct` | fire=93.7% null=0.0% range=[0.0..10.0] med=4.0 | ✅ Stable |
| `long_dn_up_pattern` | fire=4.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `long_up_dn_pattern` | fire=5.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `range_h_minus_lprev_ticks` | fire=99.9% null=0.0% range=[0.0..400.0] med=50.0 | ✅ Stable |
| `range_hprev_minus_l_ticks` | fire=99.9% null=0.0% range=[-2.0..518.0] med=55.0 | ✅ Stable |

## SWINGS - high/low / Wyckoff structure

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `dist_swing_high` | fire=99.9% null=0.0% range=[-211.0..1558.0] med=264.0 | ✅ Stable |
| `dist_swing_low` | fire=99.9% null=0.0% range=[-806.0..1215.0] med=-49.0 | ✅ Stable |
| `swing_range_ticks` | fire=100.0% null=0.0% range=[-262.0..1579.0] med=329.0 | ✅ Stable |
| `price_vs_swing_mid` | fire=99.9% null=0.0% range=[-1.0..1.0] med=-1.0 | ✅ Stable |
| `new_swing_high` | fire=0.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `new_swing_low` | fire=2.0% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `dist_swing_high` | fire=99.9% null=0.0% range=[-389.5..52.75] med=-63.5 | ✅ Stable |
| `dist_swing_low` | fire=99.9% null=0.0% range=[-303.75..201.5] med=20.5 | ✅ Stable |
| `dist_last_swing_high_pct` | fire=99.9% null=0.0% range=[-1.352..0.175] med=-0.212 | ✅ Stable |
| `dist_last_swing_low_pct` | fire=99.9% null=0.0% range=[-1.044..0.691] med=0.068 | ✅ Stable |
| `bars_since_last_swing_high` | fire=100.0% null=0.0% range=[10.0..158.0] med=30.0 | ✅ Stable |
| `bars_since_last_swing_low` | fire=100.0% null=0.0% range=[10.0..144.0] med=29.0 | ✅ Stable |
| `last_swing_high_session` | fire=62.9% null=0.0% range=[0.0..3.0] med=1.0 | ✅ OK |
| `last_swing_low_session` | fire=64.3% null=0.0% range=[0.0..3.0] med=1.0 | ✅ OK |
| `swing_high_active_lag10` | fire=2.5% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `swing_low_active_lag10` | fire=2.8% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `_last_swing_high_price` | fire=100.0% null=0.0% range=[28875.5..30422.0] med=30194.25 | ✅ Stable |
| `_last_swing_low_price` | fire=100.0% null=0.0% range=[28781.25..30255.0] med=30120.25 | ✅ Stable |
| `equal_highs_detected` | fire=0.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `equal_lows_detected` | fire=0.2% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `liquidity_sweep_high_lag5` | fire=2.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `liquidity_sweep_low_lag5` | fire=6.0% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |

## Game Changers (Dalton Open/Day/Profile)

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `open_type` | fire=100.0% null=0.0% range=[1.0..10.0] med=1.0 | ✅ Stable |
| `open_zone` | fire=100.0% null=0.0% range=[3.0..5.0] med=3.0 | ✅ Stable |
| `open_bias_conf` | fire=100.0% null=0.0% range=[0.85..0.9] med=0.85 | ✅ Stable |
| `open_direction` | fire=92.2% null=0.0% range=[-1.0..1.0] med=1.0 | ✅ Stable |
| `day_type` | fire=100.0% null=0.0% range=[2.0..2.0] med=2.0 | ✅ Stable |
| `rule_80pct` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `trend_day_probability` | fire=28.3% null=0.0% range=[0.0..0.35] med=0.0 | ⚠️ Sparse |
| `profile_shape` | fire=100.0% null=0.0% range=[2.0..3.0] med=3.0 | ✅ Stable |
| `profile_skew` | fire=100.0% null=0.0% range=[-0.193..0.534] med=0.226 | ✅ Stable |
| `poc_position` | fire=100.0% null=0.0% range=[0.039..0.978] med=0.967 | ✅ Stable |
| `volume_imbalance` | fire=100.0% null=0.0% range=[0.411..8.465] med=1.718 | ✅ Stable |
| `is_double_dist` | fire=99.6% null=0.0% range=[0.0..1.0] med=1.0 | ✅ Stable |
| `poc_separation_ticks` | fire=99.6% null=0.0% range=[0.0..2940.0] med=52.0 | ✅ Stable |
| `single_print_mid` | fire=100.0% null=0.0% range=[29143.12..30497.88] med=30327.75 | ✅ Stable |
| `single_print_count` | fire=100.0% null=0.0% range=[17.0..495.0] med=316.0 | ✅ Stable |
| `profile_hvn_dominant` | fire=100.0% null=0.0% range=[29150.0..30585.0] med=30585.0 | ✅ Stable |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `open_type` | fire=50.0% null=0.0% range=[0.0..9.0] med=9.0 | ✅ OK |
| `day_type` | fire=100.0% null=0.0% range=[2.0..2.0] med=2.0 | ✅ Stable |
| `profile_shape` | ABSENT | ❌ |
| `open_zone` | fire=50.0% null=0.0% range=[0.0..1.0] med=1.0 | ✅ OK |
| `open_direction` | fire=50.0% null=0.0% range=[-1.0..0.0] med=0.0 | ✅ OK |
| `open_bias_conf` | fire=50.0% null=0.0% range=[0.0..0.65] med=0.65 | ✅ OK |
| `ctx_day_type_intensity` | fire=32.7% null=0.0% range=[-1.0..0.0] med=0.0 | ✅ OK |
| `ctx_trend_day_score` | fire=99.4% null=0.0% range=[0.0..0.6] med=0.35 | ✅ Stable |

## MA + Booleans

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `ma_trend` | fire=100.0% null=0.0% range=[1.0..1.0] med=1.0 | ✅ Stable |
| `vwap_ma_align` | fire=2.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `bool_above_cur_vpoc` | fire=4.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `bool_above_prev_vpoc` | fire=6.5% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `bool_above_vwap_d` | fire=2.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `bool_above_vwap_w` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bool_above_vwap_m` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bool_above_mq_hvl` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bool_above_mq_call` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bool_near_level` | fire=12.5% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `bool_ib_inside` | fire=7.5% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `bool_session_early` | fire=76.1% null=0.0% range=[0.0..1.0] med=1.0 | ✅ OK |
| `vwap_triple_align` | fire=97.6% null=0.0% range=[-1.0..0.0] med=-1.0 | ✅ Stable |
| `bool_va_confluence` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bool_gex_flip_zone` | fire=42.2% null=0.0% range=[0.0..1.0] med=0.0 | ✅ OK |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `above_open_830` | fire=0.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `above_open_930` | fire=0.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `above_asia_open` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `above_london_open` | fire=23.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `above_ny_open` | fire=0.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `above_after_open` | fire=0.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `is_new_sess_high` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `is_new_sess_low` | fire=12.5% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `is_new_cash_high` | fire=0.2% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `is_new_cash_low` | fire=7.8% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `vwap_d_cross_up` | fire=1.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `vwap_d_cross_dn` | fire=1.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `premium_zone` | fire=0.7% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `discount_zone` | fire=99.3% null=0.0% range=[0.0..1.0] med=1.0 | ✅ Stable |
| `bool_gex_flip_zone` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |

## HVN / LVN session

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `dist_session_hvn_above` | fire=88.0% null=12.0% range=[1.0..1500.0] med=93.0 | ✅ OK |
| `dist_session_hvn_below` | fire=44.1% null=55.9% range=[1.0..500.0] med=22.0 | ❌ Trop null |
| `dist_session_lvn_above` | fire=88.9% null=11.1% range=[1.0..1434.0] med=156.0 | ✅ OK |
| `dist_session_lvn_below` | fire=70.4% null=29.6% range=[1.0..596.0] med=98.0 | ✅ OK |
| `session_hvn_count` | fire=13.5% null=0.0% range=[0.0..10.0] med=0.0 | ⚠️ Sparse |
| `session_lvn_count` | fire=12.6% null=0.0% range=[0.0..10.0] med=0.0 | ⚠️ Sparse |
| `lvn_between` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `hvn_between` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `lvn_confluence_count` | fire=16.5% null=0.0% range=[0.0..5.0] med=0.0 | ⚠️ Sparse |

### Databento : RIEN

## Divergences

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `delta_divergence` | fire=3.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `delta_div_buy` | fire=31.7% null=0.0% range=[0.0..1.0] med=0.0 | ✅ OK |
| `delta_div_sell` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `delta_div_buy_clean` | fire=9.0% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `delta_div_sell_clean` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `delta_divergence_clean` | fire=9.0% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `n_delta_div_buy_zones_active` | fire=100.0% null=0.0% range=[1.0..12.0] med=2.0 | ✅ Stable |
| `n_delta_div_sell_zones_active` | fire=100.0% null=0.0% range=[9.0..9.0] med=9.0 | ✅ Stable |
| `dist_delta_div_buy_nearest_pct` | fire=98.7% null=0.0% range=[-0.474..5.146] med=-0.016 | ✅ Stable |
| `dist_delta_div_sell_nearest_pct` | fire=100.0% null=0.0% range=[1.238..6.354] med=1.631 | ✅ Stable |
| `n_delta_div_buy_cluster_within_0_2pct` | fire=59.2% null=0.0% range=[0.0..8.0] med=1.0 | ✅ OK |
| `n_delta_div_sell_cluster_within_0_2pct` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `retest_high_delta_div` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `retest_low_delta_div` | fire=20.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `div_confluence_with_regime` | fire=9.0% null=0.0% range=[0.0..3.0] med=0.0 | ⚠️ Sparse |
| `div_regime_proxy_ok` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `div_at_key_level_ticks` | fire=9.0% null=91.0% range=[0.25..237.25] med=21.75 | ❌ Trop null |
| `div_confluence_dmp` | fire=9.0% null=0.0% range=[0.0..3.0] med=0.0 | ⚠️ Sparse |
| `delta_div_strength` | fire=9.0% null=0.0% range=[0.0..799.0] med=0.0 | ⚠️ Sparse |
| `ctx_div_density_20` | fire=38.0% null=0.0% range=[0.0..12.0] med=0.0 | ✅ OK |
| `ctx_bars_since_div` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `ctx_div_at_swing` | fire=1.2% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `ctx_price_delta_div_3` | fire=77.2% null=0.0% range=[-1.0..1.0] med=0.0 | ✅ OK |

## Rotations + Retests

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `rotation_up` | fire=17.8% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `rotation_dn` | fire=23.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `rotation_zz_osc` | fire=98.3% null=0.0% range=[-95.25..63.0] med=0.0 | ✅ Stable |
| `retest_high_count` | fire=6.8% null=0.0% range=[0.0..2.0] med=0.0 | ⚠️ Sparse |
| `retest_low_count` | fire=28.1% null=0.0% range=[0.0..3.0] med=0.0 | ⚠️ Sparse |
| `retest_high_delta_div` | fire=0.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `retest_low_delta_div` | fire=0.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `bars_since_retest_high` | fire=6.8% null=93.2% range=[1.0..25.0] med=8.0 | ❌ Trop null |
| `bars_since_retest_low` | fire=28.1% null=71.9% range=[1.0..47.0] med=10.0 | ❌ Trop null |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `rotation_up` | fire=17.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `rotation_dn` | fire=23.5% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `ctx_rotation_factor_20` | fire=34.5% null=0.0% range=[0.0..9.0] med=0.0 | ✅ OK |
| `retest_high_delta_div` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `retest_low_delta_div` | fire=20.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `bars_since_retest_high` | fire=82.0% null=0.0% range=[0.0..314.0] med=26.0 | ✅ OK |
| `bars_since_retest_low` | fire=49.1% null=0.0% range=[0.0..124.0] med=0.0 | ✅ OK |

## Spike origins (Databento only)

### Sierra : RIEN

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `spike_detected_lag3` | fire=14.8% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `n_spike_origins_active` | fire=100.0% null=0.0% range=[9.0..79.0] med=12.0 | ✅ Stable |
| `dist_last_spike_origin_pct` | fire=100.0% null=0.0% range=[-0.326..0.659] med=0.024 | ✅ Stable |
| `n_spike_origins_cluster_within_0_2pct` | fire=82.6% null=0.0% range=[0.0..6.0] med=2.0 | ✅ OK |
| `bars_since_last_spike` | fire=85.2% null=0.0% range=[0.0..251.0] med=14.0 | ✅ OK |

## RVOL (Relative Volume)

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `rvol` | fire=100.0% null=0.0% range=[0.159..7.977] med=0.908 | ✅ Stable |
| `rvol_zscore` | fire=100.0% null=0.0% range=[-1.903..4.298] med=-0.238 | ✅ Stable |
| `rvol_buy` | fire=2.0% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `rvol_sell` | fire=2.2% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `rvol_absorb_buy` | fire=1.0% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `rvol_absorb_sell` | fire=0.3% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `rvol` | fire=100.0% null=0.0% range=[0.159..7.977] med=0.92 | ✅ Stable |
| `rvol_zscore` | fire=100.0% null=0.0% range=[-1.855..4.19] med=-0.221 | ✅ Stable |
| `rvol_regime` | fire=72.9% null=0.0% range=[0.0..4.0] med=1.0 | ✅ OK |
| `rvol_buy` | fire=1.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `rvol_sell` | fire=1.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `rvol_buy_strong` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `rvol_sell_strong` | fire=0.2% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `rvol_absorb_buy` | fire=1.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `rvol_absorb_sell` | fire=1.9% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `rvol_extreme` | fire=0.6% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `ctx_rvol_session` | fire=100.0% null=0.0% range=[0.143..8.309] med=0.893 | ✅ Stable |

## Sessions detection fine

### Sierra

| Feature | Stats | Verdict |
|---|---|---|
| `session` | fire=60.8% null=0.0% range=[0.0..2.0] med=1.0 | ✅ OK |
| `session_id` | null=0.0%, vals={'Asia': 540, 'US': 478, 'London': 360} | ✅ Varies |

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `session_id` | fire=66.7% null=0.0% range=[0.0..3.0] med=1.0 | ✅ OK |
| `is_in_asia` | fire=33.3% null=0.0% range=[0.0..1.0] med=0.0 | ✅ OK |
| `is_in_london` | fire=31.0% null=0.0% range=[0.0..1.0] med=0.0 | ✅ OK |
| `is_in_us_cash` | fire=31.0% null=0.0% range=[0.0..1.0] med=0.0 | ✅ OK |
| `is_in_us_after` | fire=4.8% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `session_date` | null=0.0%, vals={'2026-06-05': 1260} | ⚠️ FIGE |
| `session_date_trading` | null=0.0%, vals={'2026-06-05': 1260} | ⚠️ FIGE |
| `session_segment` | fire=31.0% null=0.0% range=[0.0..3.0] med=0.0 | ✅ OK |
| `asia_high` | fire=100.0% null=0.0% range=[30422.0..30422.0] med=30422.0 | ✅ Stable |
| `asia_low` | fire=100.0% null=0.0% range=[30052.25..30233.75] med=30052.25 | ✅ Stable |
| `dist_asia_high_pct` | fire=100.0% null=0.0% range=[-5.646..-0.564] med=-0.953 | ✅ Stable |
| `dist_asia_low_pct` | fire=99.9% null=0.0% range=[-4.362..0.659] med=0.209 | ✅ Stable |
| `london_high` | fire=66.7% null=33.3% range=[30127.0..30259.0] med=30259.0 | ✅ OK |
| `london_low` | fire=66.7% null=33.3% range=[30013.0..30111.0] med=30013.0 | ✅ OK |
| `dist_london_high_pct` | fire=66.6% null=33.3% range=[-5.08..0.0] med=-1.227 | ✅ OK |
| `dist_london_low_pct` | fire=66.6% null=33.3% range=[-4.225..0.626] med=-0.404 | ✅ OK |
| `us_high` | fire=35.7% null=64.3% range=[30059.5..30100.5] med=30100.5 | ❌ Trop null |
| `us_low` | fire=35.7% null=64.3% range=[28974.25..29998.75] med=29377.0 | ❌ Trop null |
| `dist_us_high_pct` | fire=35.7% null=64.3% range=[-4.529..-0.005] med=-2.231 | ❌ Trop null |
| `dist_us_low_pct` | fire=35.6% null=64.3% range=[-0.618..0.691] med=0.11 | ❌ Trop null |
| `after_high` | fire=4.8% null=95.2% range=[29042.25..29042.25] med=29042.25 | ❌ Trop null |
| `after_low` | fire=4.8% null=95.2% range=[28781.25..29015.0] med=28800.0 | ❌ Trop null |
| `dist_after_high_pct` | fire=4.8% null=95.2% range=[-0.854..-0.042] med=-0.722 | ❌ Trop null |
| `dist_after_low_pct` | fire=4.8% null=95.2% range=[0.009..0.267] med=0.096 | ❌ Trop null |
| `asia_open` | fire=100.0% null=0.0% range=[30414.0..30414.0] med=30414.0 | ✅ Stable |
| `asia_open_approximate` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `dist_asia_open_pct` | fire=100.0% null=0.0% range=[-5.618..-0.537] med=-0.927 | ✅ Stable |
| `london_open` | fire=66.7% null=33.3% range=[30124.25..30124.25] med=30124.25 | ✅ OK |
| `london_open_approximate` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `dist_london_open_pct` | fire=66.7% null=33.3% range=[-4.612..0.421] med=-0.776 | ✅ OK |
| `ny_open` | fire=35.7% null=64.3% range=[30035.75..30035.75] med=30035.75 | ❌ Trop null |
| `ny_open_approximate` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `dist_ny_open_pct` | fire=35.7% null=64.3% range=[-4.304..0.204] med=-2.011 | ❌ Trop null |
| `after_open` | fire=4.8% null=95.2% range=[29016.25..29016.25] med=29016.25 | ❌ Trop null |
| `after_open_approximate` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `dist_after_open_pct` | fire=4.8% null=95.2% range=[-0.764..0.047] med=-0.632 | ❌ Trop null |
| `pct_in_range` | fire=99.8% null=0.0% range=[0.0..53.888] med=19.27 | ✅ Stable |
| `ctx_session_phase` | fire=61.9% null=0.0% range=[0.0..5.0] med=2.0 | ✅ OK |
| `is_cash_session` | fire=31.0% null=0.0% range=[0.0..1.0] med=0.0 | ✅ OK |
| `is_ib_window` | fire=4.8% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `mins_et` | fire=99.9% null=0.0% range=[0.0..1439.0] med=630.0 | ✅ Stable |

## News (Databento only)

### Sierra : RIEN

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `is_news_715` | fire=0.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `within_news_715_5m` | fire=0.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `is_news_730` | fire=0.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `within_news_730_5m` | fire=0.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `is_news_830` | fire=0.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `within_news_830_5m` | fire=0.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `is_news_845` | fire=0.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `within_news_845_5m` | fire=0.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `is_news_900` | fire=0.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `within_news_900_5m` | fire=0.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `is_news_930` | fire=0.1% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `within_news_930_5m` | fire=0.4% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `mins_since_news` | fire=99.5% null=0.0% range=[-1.0..869.0] med=60.0 | ✅ Stable |
| `mins_to_next_news` | fire=100.0% null=0.0% range=[-1.0..435.0] med=-1.0 | ✅ Stable |

## Cross-instrument (im_*) - Databento only

### Sierra : RIEN

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `im_cross_delta_agreement_5` | fire=99.4% null=0.0% range=[0.0..1.0] med=0.6 | ✅ Stable |
| `im_cross_delta_weighted_5` | fire=99.4% null=0.0% range=[0.0..365.0] med=19.6 | ✅ Stable |
| `im_smt_divergence` | fire=0.6% null=0.0% range=[-1.0..1.0] med=0.0 | ⚠️ Rare |
| `im_delta_day_divergence` | ABSENT | ❌ |
| `im_price_ratio_slope_10` | fire=99.9% null=0.0% range=[-0.001..0.000979] med=-0.0 | ✅ Stable |
| `im_volume_lead` | ABSENT | ❌ |
| `im_rolling_correlation_10` | fire=100.0% null=0.0% range=[-0.297..0.999] med=0.961 | ✅ Stable |
| `im_ltr_slope_diff` | ABSENT | ❌ |
| `im_cross_open_signal` | fire=50.0% null=0.0% range=[-0.65..0.0] med=0.0 | ✅ OK |
| `im_open_type_agreement` | fire=50.0% null=0.0% range=[0.0..1.0] med=1.0 | ✅ OK |

## Daily extremes + naked POC

### Sierra : RIEN

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `mq_1d_min` | fire=100.0% null=0.0% range=[30121.199..30240.789] med=30121.199 | ✅ Stable |
| `mq_1d_max` | fire=100.0% null=0.0% range=[30855.301..31025.711] med=30855.301 | ✅ Stable |
| `dist_1d_min_ticks` | fire=100.0% null=0.0% range=[-521.2..5299.8] med=184.2 | ✅ Stable |
| `dist_1d_max_ticks` | fire=100.0% null=0.0% range=[2415.2..8236.2] med=3270.8 | ✅ Stable |
| `dist_1d_min_ticks_pct` | fire=100.0% null=0.0% range=[-0.431..4.601] med=0.152 | ✅ Stable |
| `dist_1d_max_ticks_pct` | fire=100.0% null=0.0% range=[1.996..7.15] med=2.711 | ✅ Stable |
| `dist_naked_poc_nearest_pct` | fire=100.0% null=0.0% range=[-0.666..6.115] med=-0.27 | ✅ Stable |
| `atr_regime_zscore_60d` | ABSENT | ❌ |

## CTX rolling features (Databento extensive)

### Sierra : RIEN

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `ctx_climax_signal` | fire=34.6% null=0.0% range=[-1.0..1.0] med=0.0 | ✅ OK |
| `ctx_failed_auction` | fire=3.7% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `ctx_absorption_score_5` | fire=99.7% null=0.0% range=[0.0..1.0] med=0.6 | ✅ Stable |
| `ctx_absorption_streak_5` | fire=38.7% null=0.0% range=[-4.0..3.0] med=0.0 | ✅ OK |
| `ctx_instant_absorption` | fire=11.6% null=0.0% range=[-1.0..1.0] med=0.0 | ⚠️ Sparse |
| `ctx_delta_exhaustion` | fire=98.9% null=0.0% range=[0.0..1.0] med=0.31 | ✅ Stable |
| `ctx_momentum_exhaustion` | fire=52.3% null=0.0% range=[-1.0..1.0] med=0.0 | ✅ OK |
| `ctx_poor_high` | fire=100.0% null=0.0% range=[1.0..1.0] med=1.0 | ✅ Stable |
| `ctx_poor_low` | fire=62.7% null=0.0% range=[0.0..1.0] med=1.0 | ✅ OK |
| `ctx_excess_high_bars` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `ctx_excess_low_bars` | fire=49.6% null=0.0% range=[0.0..11.0] med=0.0 | ✅ OK |
| `ctx_double_top_trap` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `ctx_failed_auction` | fire=3.7% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Rare |
| `ctx_vol_sell_buy_ratio_5` | fire=100.0% null=0.0% range=[0.12..10.494] med=1.0 | ✅ Stable |
| `ctx_vol_slope_5` | fire=99.8% null=0.0% range=[-3054.0..2735.3] med=-0.9 | ✅ Stable |
| `ctx_vol_z_5` | fire=99.9% null=0.0% range=[-1.773..1.788] med=-0.205 | ✅ Stable |
| `ctx_finish_strength_mean_5` | fire=100.0% null=0.0% range=[-70.896..61.681] med=-6.153 | ✅ Stable |
| `ctx_dist_vwap_velocity` | fire=100.0% null=0.0% range=[-216.274..142.825] med=3.546 | ✅ Stable |
| `ctx_vwap_slope_accel` | fire=100.0% null=0.0% range=[-20.832..21.542] med=-0.002 | ✅ Stable |
| `ctx_va_position_velocity` | fire=73.1% null=0.0% range=[-0.3..0.652] med=0.0 | ✅ OK |
| `ctx_side_flip_count_10` | fire=13.5% null=0.0% range=[0.0..5.0] med=0.0 | ⚠️ Sparse |
| `ctx_range_vs_atr_10` | fire=100.0% null=0.0% range=[0.618..6.247] med=2.352 | ✅ Stable |
| `ctx_price_slope_5` | fire=99.5% null=0.0% range=[-34.575..24.7] med=-0.925 | ✅ Stable |

## Regime engine (Databento computed)

### Sierra : RIEN

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `regime_mode` | null=0.0%, vals={'TREND': 1084, 'NORMAL': 176} | ⚠️ Peu varies |
| `regime_favor` | null=0.0%, vals={'LONG': 682, 'NEUTRE': 570, 'SHORT': 8} | ✅ Varies |
| `regime_confidence` | fire=86.0% null=0.0% range=[0.0..0.33] med=0.08 | ✅ OK |
| `regime_actionable` | fire=22.5% null=0.0% range=[0.0..1.0] med=0.0 | ⚠️ Sparse |
| `regime_vol` | null=0.0%, vals={'NORMAL': 1260} | ⚠️ FIGE |
| `regime_trend_votes` | fire=100.0% null=0.0% range=[4.0..6.0] med=4.0 | ✅ Stable |
| `regime_range_votes` | fire=100.0% null=0.0% range=[2.0..4.0] med=3.0 | ✅ Stable |

## Roll / Maintenance

### Sierra : RIEN

### Databento

| Feature | Stats | Verdict |
|---|---|---|
| `is_roll_day` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `days_since_roll` | ABSENT | ❌ |
| `roll_phase` | ABSENT | ❌ |
| `data_quality_flag` | fire=0.0% null=0.0% range=[0.0..0.0] med=0.0 | ❌ MORT |
| `bars_since_boot` | fire=100.0% null=0.0% range=[12715.0..13974.0] med=13345.0 | ✅ Stable |
