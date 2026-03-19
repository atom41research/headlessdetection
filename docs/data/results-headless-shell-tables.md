---
layout: default
title: Benchmark Tables
parent: Raw Data
nav_order: 3
---

# Chrome Headless Modes — Tables Summary

All tables from the full analysis, collected in one document.

---

## Experimental Setup

| Parameter                  | Value                                                                            |
|----------------------------|----------------------------------------------------------------------------------|
| URLs tested                | 965 (deduplicated from Tranco top-1000)                                          |
| Runs per mode              | 2 (independent container launches)                                               |
| Data points per mode       | 1,930                                                                            |
| Container resource limits  | 4 CPUs, 8 GB RAM, 8 GB shared memory                                            |
| Sampling interval          | 250 ms                                                                           |
| Settle time after load     | 2.0 s                                                                            |
| Navigation timeout         | 10,000 ms                                                                        |
| Per-URL timeout            | 60 s                                                                             |
| Navigation wait condition  | `domcontentloaded`                                                               |
| Viewport                   | 1280 x 720                                                                       |
| Browser flags              | `--no-sandbox --disable-blink-features=AutomationControlled --disable-crashpad`  |
| User-Agent override        | Headful Chrome UA applied to all modes                                           |

### Modes Under Test

| Mode               | Binary                  | Chrome Version   | Channel                    |
|--------------------|-------------------------|------------------|----------------------------|
| **headless**       | Google Chrome stable    | 145.0.7632.159   | `chrome`                   |
| **headful**        | Google Chrome stable    | 145.0.7632.159   | `chrome`                   |
| **headless-shell** | chrome-headless-shell   | 145.0.7632.6     | `chromium-headless-shell`  |

---

## Overhead Ratios (Fresh Mode)

#### Resource Metrics

| Metric                          |   HF/HL |   HF/Shell |   HL/Shell |
|---------------------------------|--------:|-----------:|-----------:|
| Container Active Memory (MB)    |   1.05x |      1.35x |      1.29x |
| Container Total Memory (MB)     |   1.17x |      1.50x |      1.28x |
| Container CPU%                  |   1.07x |      1.35x |      1.26x |
| Chrome USS (MB)                 |   1.00x |      1.24x |      1.24x |
| Chrome USS peak (MB)            |   1.00x |      1.22x |      1.22x |
| Chrome RSS (MB)                 |   1.04x |      1.70x |      1.64x |
| Chrome CPU% (avg)               |   1.04x |      1.27x |      1.22x |
| Chrome CPU% (peak)              |   1.02x |      1.17x |      1.14x |
| Process count (peak)            |   1.00x |      1.46x |      1.46x |
| Baseline-subtracted Active (MB) |   0.93x |      1.17x |      1.27x |

#### Timing Metrics

| Metric                          |   HF/HL |   HF/Shell |   HL/Shell |
|---------------------------------|--------:|-----------:|-----------:|
| Wall-clock load (ms)            |   1.02x |      0.99x |      0.97x |
| DNS (ms)                        |   1.06x |      0.95x |      0.90x |
| Connect (ms)                    |   1.00x |      0.79x |      0.79x |
| TTFB (ms)                       |   1.03x |      0.92x |      0.89x |
| Response (ms)                   |   0.99x |      0.92x |      0.93x |
| DOM Interactive (ms)            |   1.01x |      0.96x |      0.94x |
| DOM Content Loaded (ms)         |   1.01x |      0.97x |      0.95x |
| DOM Complete (ms)               |   1.03x |      0.97x |      0.94x |
| Load Event (ms)                 |   1.03x |      0.97x |      0.94x |

#### Reuse-Browser Mode Ratios

| Metric                          |   HF/HL |   HF/Shell |   HL/Shell |
|---------------------------------|--------:|-----------:|-----------:|
| Container Active Memory (MB)    |   1.11x |      1.06x |      0.96x |
| Container Total Memory (MB)     |   1.13x |      1.10x |      0.97x |
| Container CPU%                  |   1.03x |      1.20x |      1.17x |
| Chrome USS (MB)                 |   1.11x |      1.05x |      0.95x |
| Chrome RSS (MB)                 |   1.10x |      1.28x |      1.16x |
| Chrome CPU% (avg)               |   1.01x |      1.19x |      1.18x |
| Process count (peak)            |   1.05x |      1.15x |      1.09x |
| Wall-clock load (ms)            |   1.00x |      1.00x |      1.01x |

---

## Mean Values (Fresh Mode)

#### Resource Metrics

| Metric                          |   Headless |   Headful |   Shell |
|---------------------------------|-----------:|----------:|--------:|
| Container Active Memory (MB)    |      563.2 |     590.7 |   436.0 |
| Container Total Memory (MB)     |      645.0 |     753.7 |   502.1 |
| Container CPU%                  |       79.5 |      85.4 |    63.3 |
| Chrome USS (MB)                 |      439.7 |     440.3 |   354.3 |
| Chrome USS peak (MB)            |      504.0 |     505.0 |   414.7 |
| Chrome RSS (MB)                 |    1,268.2 |   1,314.1 |   771.5 |
| Chrome CPU% (avg)               |       57.3 |      59.6 |    47.0 |
| Chrome CPU% (peak)              |      156.2 |     159.3 |   136.5 |
| Process count (peak)            |       10.5 |      10.5 |     7.2 |
| Baseline-subtracted Active (MB) |       81.6 |      75.5 |    64.3 |

#### Timing Metrics

| Metric                          |   Headless |   Headful |     Shell |
|---------------------------------|-----------:|----------:|----------:|
| Wall-clock load (ms)            |    3,386.8 |   3,449.5 |   3,484.1 |
| DNS (ms)                        |       89.4 |      94.7 |      99.8 |
| Connect (ms)                    |      117.8 |     117.9 |     150.0 |
| TTFB (ms)                       |      559.4 |     573.7 |     626.3 |
| Response (ms)                   |      101.6 |     100.2 |     108.9 |
| DOM Interactive (ms)            |    1,125.8 |   1,141.8 |   1,192.6 |
| DOM Content Loaded (ms)         |    1,265.3 |   1,282.2 |   1,326.5 |
| DOM Complete (ms)               |    1,681.8 |   1,728.2 |   1,785.9 |
| Load Event (ms)                 |    1,684.5 |   1,731.4 |   1,788.4 |

#### Reuse-Browser Mode Means

| Metric                          |   HL-Reuse |   HF-Reuse |   Shell-Reuse |
|---------------------------------|-----------:|-----------:|--------------:|
| Container Active Memory (MB)    |    3,649.6 |    4,033.5 |       3,808.8 |
| Container Total Memory (MB)     |    3,843.6 |    4,335.1 |       3,948.9 |
| Container CPU%                  |      116.0 |      119.2 |          99.5 |
| Chrome USS (MB)                 |    3,432.4 |    3,819.7 |       3,625.0 |
| Chrome RSS (MB)                 |   11,327.5 |   12,492.9 |       9,759.1 |
| Chrome CPU% (avg)               |       59.1 |       59.5 |          49.9 |
| Process count (peak)            |       62.8 |       66.2 |          57.7 |
| Wall-clock load (ms)            |    3,464.6 |    3,447.8 |       3,432.4 |

---

## Fresh Mode — Aggregate Statistics

| Metric                              | Statistic          |   Headless |   Headful |   Headless-Shell |
|--------------------------------------|--------------------|------------|-----------|------------------|
| **Valid runs**                       | count              |      1,897 |     1,897 |            1,871 |
| **Errors**                          | count (non-timeout) |          6 |        -3 |               27 |
| **Timeouts**                        | count              |         27 |        36 |               32 |
|                                      |                    |            |           |                  |
| **Container Active (MB)**           | mean               |      563.2 |     590.7 |            436.0 |
|                                      | median             |      576.3 |     595.2 |            449.5 |
|                                      | stdev              |      134.2 |     143.1 |            106.1 |
|                                      | min                |      248.4 |     257.8 |            141.5 |
|                                      | max                |    1,161.9 |   1,191.1 |            828.9 |
|                                      | P5                 |      330.0 |     361.4 |            258.5 |
|                                      | P95                |      769.0 |     800.8 |            589.4 |
| **Container Total (MB)**            | mean               |      645.0 |     753.7 |            502.1 |
|                                      | median             |      660.7 |     747.6 |            512.6 |
|                                      | stdev              |      140.1 |     153.0 |            116.1 |
|                                      | min                |      340.3 |     329.1 |            186.9 |
|                                      | max                |    1,366.2 |   1,476.3 |            931.8 |
|                                      | P5                 |      404.4 |     527.5 |            310.2 |
|                                      | P95                |      848.3 |     987.5 |            677.7 |
| **Container CPU%**                  | mean               |       79.5 |      85.4 |             63.3 |
|                                      | median             |       65.8 |      72.3 |             52.4 |
|                                      | stdev              |       56.5 |      56.1 |             48.0 |
|                                      | min                |        9.5 |      10.8 |              3.0 |
|                                      | max                |      390.7 |     329.5 |            341.9 |
|                                      | P5                 |       17.0 |      20.4 |              9.3 |
|                                      | P95                |      192.4 |     201.1 |            154.5 |
|                                      |                    |            |           |                  |
| **Chrome USS (MB)**                 | mean               |      439.7 |     440.3 |            354.3 |
|                                      | median             |      433.0 |     432.0 |            347.2 |
|                                      | stdev              |       83.8 |      79.9 |             71.8 |
|                                      | min                |      196.6 |     192.5 |            118.8 |
|                                      | max                |    1,068.5 |   1,074.5 |            846.5 |
|                                      | P5                 |      320.9 |     335.3 |            253.4 |
|                                      | P95                |      575.8 |     567.8 |            469.8 |
| **Chrome USS peak (MB)**            | mean               |      504.0 |     505.0 |            414.7 |
|                                      | median             |      482.5 |     482.0 |            398.5 |
|                                      | P5                 |      331.9 |     341.7 |            257.8 |
|                                      | P95                |      755.8 |     753.9 |            621.6 |
| **Chrome RSS (MB)**                 | mean               |    1,268.2 |   1,314.1 |            771.5 |
|                                      | median             |    1,185.1 |   1,231.7 |            756.1 |
|                                      | stdev              |      358.7 |     344.9 |            152.2 |
|                                      | min                |      493.6 |     582.1 |            260.5 |
|                                      | max                |    2,382.6 |   1,972.2 |          1,185.6 |
|                                      | P5                 |      928.1 |     973.3 |            565.7 |
|                                      | P95                |    1,883.4 |   1,948.1 |          1,023.6 |
| **Chrome CPU% (avg)**               | mean               |       57.3 |      59.6 |             47.0 |
|                                      | median             |       44.3 |      48.4 |             37.4 |
|                                      | min                |        2.8 |       3.6 |              0.1 |
|                                      | max                |      361.6 |     280.3 |            294.5 |
| **Chrome CPU% (peak)**              | mean               |      156.2 |     159.3 |            136.5 |
|                                      | median             |      152.1 |     157.1 |            133.7 |
| **Process count (peak)**            | mean               |       10.5 |      10.5 |              7.2 |
|                                      | median             |         10 |        10 |                7 |
|                                      |                    |            |           |                  |
| **Baseline-subtracted Active (MB)** | mean               |       81.6 |      75.5 |             64.3 |
|                                      | median             |       66.7 |      61.2 |             54.2 |
|                                      | stdev              |       69.7 |      69.4 |             56.3 |

---

## Fresh Mode — Navigation Timing

| Milestone                     | Stat       |   Headless |   Headful |   Headless-Shell |
|-------------------------------|------------|------------|-----------|------------------|
| **DNS (ms)**                  | mean       |       89.4 |      94.7 |             99.8 |
|                               | median     |       54.8 |      56.0 |             66.4 |
|                               | min        |        2.5 |       0.1 |              0.6 |
|                               | max        |    3,639.3 |   1,952.6 |          1,510.5 |
|                               | P95        |      306.2 |     341.3 |            307.2 |
| **Connect (ms)**              | mean       |      117.8 |     117.9 |            150.0 |
|                               | median     |       23.2 |      20.7 |            102.6 |
|                               | min        |        0.2 |       0.3 |              0.3 |
|                               | max        |    1,250.7 |   1,329.5 |          1,759.0 |
|                               | P95        |      472.3 |     479.3 |            484.1 |
| **TTFB (ms)**                 | mean       |      559.4 |     573.7 |            626.3 |
|                               | median     |      415.6 |     431.7 |            460.2 |
|                               | min        |       24.9 |      16.5 |             33.4 |
|                               | max        |    5,417.8 |   5,831.4 |          9,737.5 |
|                               | P95        |    1,477.3 |   1,509.6 |          1,534.6 |
| **Response (ms)**             | mean       |      101.6 |     100.2 |            108.9 |
|                               | median     |       11.0 |       9.9 |              8.8 |
|                               | P95        |      437.9 |     489.4 |            496.5 |
| **DOM Interactive (ms)**      | mean       |    1,125.8 |   1,141.8 |          1,192.6 |
|                               | median     |      797.6 |     827.7 |            892.0 |
|                               | P95        |    3,131.1 |   3,118.3 |          3,147.2 |
| **DOM Content Loaded (ms)**   | mean       |    1,265.3 |   1,282.2 |          1,326.5 |
|                               | median     |      934.9 |     947.5 |          1,006.1 |
|                               | P95        |    3,573.0 |   3,561.0 |          3,606.4 |
| **DOM Complete (ms)**         | mean       |    1,681.8 |   1,728.2 |          1,785.9 |
|                               | median     |    1,436.9 |   1,510.8 |          1,597.7 |
|                               | n (fired)  |      1,454 |     1,469 |            1,466 |
| **Load Event (ms)**           | mean       |    1,684.5 |   1,731.4 |          1,788.4 |
|                               | median     |    1,436.8 |   1,514.3 |          1,604.0 |
|                               | n (fired)  |      1,452 |     1,467 |            1,464 |
|                               |            |            |           |                  |
| **Wall-clock load (ms)**      | mean       |    3,386.8 |   3,449.5 |          3,484.1 |
|                               | median     |    2,952.2 |   2,967.1 |          3,038.5 |
|                               | stdev      |    1,566.2 |   1,665.5 |          1,637.1 |
|                               | min        |    1,241.7 |   1,268.8 |          2,040.4 |
|                               | max        |   12,018.7 |  12,038.0 |         12,005.4 |
|                               | P5         |    2,208.3 |   2,214.4 |          2,235.2 |
|                               | P95        |    6,349.7 |   6,331.0 |          6,444.8 |

---

## Fresh Mode — Overhead Relative to Headful

| Metric (mean)          | Headless vs Headful         | Shell vs Headful               |
|------------------------|-----------------------------|--------------------------------|
| Container Active Memory | **-4.7%** (-27.5 MB)       | **-26.2%** (-154.7 MB)        |
| Container Total Memory  | **-14.4%** (-108.7 MB)     | **-33.4%** (-251.6 MB)        |
| Container CPU%          | **-6.9%** (-5.9 pp)        | **-25.9%** (-22.1 pp)         |
| Chrome USS              | **-0.1%** (-0.6 MB)        | **-19.5%** (-86.0 MB)         |
| Chrome RSS              | **-3.5%** (-45.9 MB)       | **-41.3%** (-542.6 MB)        |
| Chrome CPU% (avg)       | **-3.9%** (-2.3 pp)        | **-21.1%** (-12.6 pp)         |
| Process count           | **0.0%**                    | **-31.4%** (-3.3 processes)   |
| Wall-clock load time    | **-1.8%** (-62.7 ms)       | **+1.0%** (+34.6 ms)          |
| TTFB                    | **-2.5%** (-14.3 ms)       | **+9.2%** (+52.6 ms)          |
| Connect time            | **-0.1%** (-0.1 ms)        | **+27.2%** (+32.1 ms)         |

---

## Fresh Mode — Per-URL Difference Extremes vs Headful

Per-URL difference = (headless mode metric) − (headful metric). Error-free URLs only (n=910 headless, n=896 shell).

| Metric                     | Stat     | Headless − Headful                         | Shell − Headful                            |
|----------------------------|----------|--------------------------------------------|--------------------------------------------|
| **Container Active (MB)**  | min diff | **-103.0** (ixxx.com)                      | **-688.5** (ui.com)                        |
|                             | max diff | **+100.2** (deepintent.com)                | **-14.2** (uber.com)                       |
| **Container Total (MB)**   | min diff | **-276.1** (android.com)                   | **-894.1** (ui.com)                        |
|                             | max diff | **+141.9** (tradingview.com)               | **+35.2** (tradingview.com)                |
| **Container CPU%**         | min diff | **-90.8** pp (jetbrains.com)               | **-217.0** pp (autodesk.com)               |
|                             | max diff | **+282.0** pp (deepintent.com)             | **+103.8** pp (uber.com)                   |
| **Chrome USS (MB)**        | min diff | **-160.0** (android.com)                   | **-675.0** (ui.com)                        |
|                             | max diff | **+228.5** (tradingview.com)               | **+155.7** (tradingview.com)               |
| **Chrome RSS (MB)**        | min diff | **-227.5** (android.com)                   | **-1,188.1** (webmd.com)                   |
|                             | max diff | **+239.0** (w3schools.com)                 | **-163.9** (tradingview.com)               |
| **Chrome CPU% (avg)**      | min diff | **-76.8** pp (jetbrains.com)               | **-180.8** pp (autodesk.com)               |
|                             | max diff | **+282.0** pp (deepintent.com)             | **+94.3** pp (uber.com)                    |
| **Wall-clock load (ms)**   | min diff | **-4,465** (cdn.teads.tv)                  | **-4,733** (lowes.com)                     |
|                             | max diff | **+3,174** (daum.net)                      | **+4,676** (linode.com)                    |
| **TTFB (ms)**              | min diff | **-4,475** (cdn.teads.tv)                  | **-4,568** (cdn.teads.tv)                  |
|                             | max diff | **+2,936** (daum.net)                      | **+2,899** (weibo.com)                     |
| **Connect (ms)**           | min diff | **-474** (360safe.com)                     | **-530** (360safe.com)                     |
|                             | max diff | **+271** (fidelity.com)                    | **+1,065** (uidai.gov.in)                  |

---

## Reuse Mode — Aggregate Statistics

| Metric                     | Statistic          |   HL-Reuse |   HF-Reuse |   Shell-Reuse |
|----------------------------|--------------------|-----------:|------------:|--------------:|
| **Valid runs**             | count              |      1,896 |       1,894 |         1,868 |
| **Errors**                | count (non-timeout) |         12 |          16 |            32 |
| **Timeouts**              | count              |         22 |          20 |            30 |
|                            |                    |            |             |               |
| **Container Active (MB)** | mean               |    3,649.6 |     4,033.5 |       3,808.8 |
|                            | median             |    3,680.6 |     4,076.5 |       4,024.0 |
|                            | stdev              |    1,748.6 |     1,978.5 |       1,818.9 |
|                            | min                |      270.7 |       302.0 |         216.3 |
|                            | max                |    7,034.6 |     7,983.0 |       7,198.0 |
|                            | P5                 |    1,095.6 |     1,172.4 |       1,070.9 |
|                            | P95                |    6,484.7 |     7,350.0 |       6,734.0 |
| **Container Total (MB)**  | mean               |    3,843.6 |     4,335.1 |       3,948.9 |
|                            | median             |    3,878.6 |     4,349.2 |       4,160.0 |
|                            | min                |      400.7 |       509.3 |         260.7 |
|                            | max                |    7,281.7 |     8,113.8 |       7,385.2 |
| **Container CPU%**        | mean               |      116.0 |       119.2 |          99.5 |
|                            | median             |      105.1 |       108.7 |          89.0 |
|                            | stdev              |       63.5 |        60.8 |          55.7 |
|                            | min                |       13.9 |        16.7 |           9.8 |
|                            | max                |      481.0 |       386.7 |         390.5 |
|                            |                    |            |             |               |
| **Chrome USS (MB)**       | mean               |    3,432.4 |     3,819.7 |       3,625.0 |
|                            | median             |    3,464.6 |     3,829.0 |       3,829.2 |
|                            | min                |      288.3 |       312.7 |         242.2 |
|                            | max                |    6,534.8 |     7,504.2 |       6,771.1 |
| **Chrome RSS (MB)**       | mean               |   11,327.5 |    12,492.9 |       9,759.1 |
|                            | median             |   11,393.6 |    12,580.4 |       9,917.8 |
|                            | min                |      890.2 |       964.2 |         576.8 |
|                            | max                |   22,508.1 |    25,922.1 |      19,492.7 |
| **Chrome CPU% (avg)**     | mean               |       59.1 |        59.5 |          49.9 |
|                            | min                |        0.0 |         0.6 |           0.4 |
|                            | max                |      342.8 |       283.1 |         321.7 |
| **Process count (peak)**  | mean               |       62.8 |        66.2 |          57.7 |
|                            |                    |            |             |               |
| **Wall-clock load (ms)**  | mean               |    3,464.6 |     3,447.8 |       3,432.4 |
|                            | median             |    3,049.6 |     3,044.9 |       2,996.5 |
|                            | min                |    2,069.8 |     1,342.5 |       1,426.6 |
|                            | max                |   12,110.1 |    12,135.4 |      12,227.2 |

---

## Reuse Mode — Overhead Relative to Headful-Reuse

| Metric (mean)           | HL-Reuse vs HF-Reuse         | Shell-Reuse vs HF-Reuse      |
|-------------------------|-------------------------------|-------------------------------|
| Container Active Memory | **-9.5%** (-383.9 MB)        | **-5.6%** (-224.7 MB)        |
| Container CPU%          | **-2.7%** (-3.2 pp)          | **-16.5%** (-19.7 pp)        |
| Chrome USS              | **-10.1%** (-387.3 MB)       | **-5.1%** (-194.7 MB)        |
| Chrome RSS              | **-9.3%** (-1,165.4 MB)      | **-21.9%** (-2,733.8 MB)     |
| Wall-clock load time    | **+0.5%** (+16.8 ms)         | **-0.4%** (-15.4 ms)         |

---

## Reuse Mode — Per-URL Difference Extremes vs Headful-Reuse

Per-URL difference = (headless mode metric) − (headful-reuse metric). Error-free URLs only (n=927 HL-reuse, n=903 shell-reuse).

| Metric                     | Stat     | HL-Reuse − HF-Reuse                       | Shell-Reuse − HF-Reuse                    |
|----------------------------|----------|--------------------------------------------|--------------------------------------------|
| **Container Active (MB)**  | min diff | **-1,166.5** (uranai.nosv.org)             | **-950.4** (24h.com.vn)                   |
|                             | max diff | **-16.6** (adobe.com)                     | **+282.9** (optimizely.com)                |
| **Container Total (MB)**   | min diff | **-1,374.9** (upenn.edu)                  | **-1,127.8** (ladepeche.fr)               |
|                             | max diff | **-46.1** (adobe.com)                     | **+184.7** (digitalocean.com)              |
| **Container CPU%**         | min diff | **-73.9** pp (npr.org)                    | **-281.5** pp (salesforce.com)             |
|                             | max diff | **+275.7** pp (buzzfeed.com)              | **+126.6** pp (android.com)                |
| **Chrome USS (MB)**        | min diff | **-1,217.0** (uranai.nosv.org)            | **-902.5** (24h.com.vn)                   |
|                             | max diff | **-12.7** (facebook.com)                  | **+348.3** (digitalocean.com)              |
| **Chrome RSS (MB)**        | min diff | **-3,550.7** (uranai.nosv.org)            | **-6,538.5** (24h.com.vn)                 |
|                             | max diff | **-47.0** (dropbox.com)                   | **-192.1** (mozilla.org)                   |
| **Chrome CPU% (avg)**      | min diff | **-55.8** pp (npr.org)                    | **-228.7** pp (salesforce.com)             |
|                             | max diff | **+267.1** pp (deepintent.com)            | **+113.8** pp (android.com)                |
| **Wall-clock load (ms)**   | min diff | **-3,535** (ilmessaggero.it)              | **-4,376** (lowes.com)                     |
|                             | max diff | **+3,227** (vk.ru)                        | **+5,665** (linode.com)                    |
| **TTFB (ms)**              | min diff | **-3,368** (lanacion.com.ar)              | **-3,707** (lanacion.com.ar)               |
|                             | max diff | **+2,547** (academia.edu)                 | **+3,509** (home.miui.com)                 |
| **Connect (ms)**           | min diff | **-314** (vivoglobal.com)                 | **-279** (vivoglobal.com)                  |
|                             | max diff | **+758** (uidai.gov.in)                   | **+775** (heytapmobi.com)                  |

---

## Reuse Mode — Navigation Timing

| Milestone                     | Stat       |   HL-Reuse |   HF-Reuse |   Shell-Reuse |
|-------------------------------|------------|-----------:|------------:|--------------:|
| **DNS (ms)**                  | mean       |      112.9 |       109.4 |          97.6 |
|                               | median     |       76.7 |        76.2 |          61.6 |
|                               | min        |        0.4 |         0.4 |           3.4 |
|                               | max        |    2,199.3 |     1,999.7 |       3,249.2 |
| **Connect (ms)**              | mean       |      128.9 |       124.7 |         134.6 |
|                               | median     |       18.3 |        18.1 |          93.9 |
|                               | min        |        1.9 |         1.8 |           5.3 |
|                               | max        |    1,597.2 |     1,354.7 |       1,511.2 |
| **TTFB (ms)**                 | mean       |      592.7 |       594.8 |         591.2 |
|                               | median     |      470.9 |       463.2 |         434.7 |
|                               | min        |       18.5 |        14.2 |          27.1 |
|                               | max        |    5,624.3 |     5,798.2 |       9,826.7 |
| **DOM Interactive (ms)**      | mean       |    1,155.4 |     1,157.1 |       1,103.2 |
|                               | median     |      846.7 |       848.6 |         812.2 |
| **DOM Content Loaded (ms)**   | mean       |    1,307.1 |     1,301.7 |       1,238.1 |
|                               | median     |      987.1 |       978.0 |         944.2 |
| **DOM Complete (ms)**         | mean       |    1,753.4 |     1,749.6 |       1,664.1 |
|                               | median     |    1,548.3 |     1,507.8 |       1,430.4 |
| **Load Event (ms)**           | mean       |    1,756.8 |     1,753.3 |       1,667.2 |
|                               | median     |    1,554.7 |     1,511.1 |       1,433.9 |
| **Wall-clock load (ms)**      | mean       |    3,464.6 |     3,447.8 |       3,432.4 |
|                               | median     |    3,049.6 |     3,044.9 |       2,996.5 |

---

## Scaling with Page Complexity — Quartile Breakdown

886 URLs bucketed into quartiles by headless Chrome RSS. Fresh-browser mode.

#### Memory Metrics

### Container Active Memory (MB)

| Quartile        | HL RSS Range       |   Headless |   Headful |   Shell |   HL vs HF |   Shell vs HF |
|-----------------|--------------------|-----------:|----------:|--------:|-----------:|--------------:|
| Q1 (lightest)   | 848--1,002 MB      |      446.2 |     473.6 |   346.6 |      -5.8% |    **-26.8%** |
| Q2              | 1,002--1,080 MB    |      551.0 |     581.0 |   431.2 |      -5.2% |    **-25.8%** |
| Q3              | 1,080--1,179 MB    |      597.9 |     628.1 |   469.8 |      -4.8% |    **-25.2%** |
| Q4 (heaviest)   | 1,179--2,047 MB    |      658.7 |     683.1 |   502.3 |      -3.6% |    **-26.5%** |

### Container Total Memory (MB)

| Quartile        | HL RSS Range       |   Headless |   Headful |   Shell |   HL vs HF |   Shell vs HF |
|-----------------|--------------------|-----------:|----------:|--------:|-----------:|--------------:|
| Q1 (lightest)   | 848--1,002 MB      |      518.8 |     627.8 |   403.0 |     -17.4% |    **-35.8%** |
| Q2              | 1,002--1,080 MB    |      629.9 |     742.0 |   496.9 |     -15.1% |    **-33.0%** |
| Q3              | 1,080--1,179 MB    |      681.8 |     795.2 |   540.1 |     -14.3% |    **-32.1%** |
| Q4 (heaviest)   | 1,179--2,047 MB    |      751.6 |     855.6 |   576.6 |     -12.2% |    **-32.6%** |

### Chrome USS (MB)

| Quartile        | HL RSS Range       |   Headless |   Headful |   Shell |   HL vs HF |   Shell vs HF |
|-----------------|--------------------|-----------:|----------:|--------:|-----------:|--------------:|
| Q1 (lightest)   | 848--1,002 MB      |      355.3 |     362.4 |   285.6 |      -2.0% |    **-21.2%** |
| Q2              | 1,002--1,080 MB    |      417.8 |     419.1 |   340.8 |      -0.3% |    **-18.7%** |
| Q3              | 1,080--1,179 MB    |      459.2 |     459.1 |   377.5 |      +0.0% |    **-17.8%** |
| Q4 (heaviest)   | 1,179--2,047 MB    |      529.2 |     525.7 |   422.0 |      +0.7% |    **-19.7%** |

### Chrome RSS (MB)

| Quartile        | HL RSS Range       |   Headless |   Headful |   Shell |   HL vs HF |   Shell vs HF |
|-----------------|--------------------|-----------:|----------:|--------:|-----------:|--------------:|
| Q1 (lightest)   | 848--1,002 MB      |      948.3 |   1,003.0 |   598.8 |      -5.5% |    **-40.3%** |
| Q2              | 1,002--1,080 MB    |    1,040.8 |   1,089.3 |   670.4 |      -4.5% |    **-38.5%** |
| Q3              | 1,080--1,179 MB    |    1,126.9 |   1,173.0 |   717.6 |      -3.9% |    **-38.8%** |
| Q4 (heaviest)   | 1,179--2,047 MB    |    1,317.3 |   1,358.3 |   776.2 |      -3.0% |    **-42.9%** |

### Baseline-subtracted Active (MB)

| Quartile        | HL RSS Range       |   Headless |   Headful |   Shell |   HL vs HF |   Shell vs HF |
|-----------------|--------------------|-----------:|----------:|--------:|-----------:|--------------:|
| Q1 (lightest)   | 848--1,002 MB      |       20.4 |      15.7 |    18.1 |     +29.7% |       +15.4%  |
| Q2              | 1,002--1,080 MB    |       53.4 |      48.7 |    47.5 |      +9.6% |        -2.6%  |
| Q3              | 1,080--1,179 MB    |       91.2 |      84.8 |    76.5 |      +7.5% |    **-9.8%**  |
| Q4 (heaviest)   | 1,179--2,047 MB    |      164.0 |     156.8 |   121.3 |      +4.6% |    **-22.6%** |

#### CPU Metrics

### Container CPU%

| Quartile        | HL RSS Range       |   Headless |   Headful |   Shell |   HL vs HF |   Shell vs HF |
|-----------------|--------------------|-----------:|----------:|--------:|-----------:|--------------:|
| Q1 (lightest)   | 848--1,002 MB      |       28.9 |      34.0 |    22.9 |     -15.2% |    **-32.6%** |
| Q2              | 1,002--1,080 MB    |       58.7 |      65.9 |    50.2 |     -10.8% |    **-23.7%** |
| Q3              | 1,080--1,179 MB    |       90.3 |      96.6 |    76.0 |      -6.5% |    **-21.3%** |
| Q4 (heaviest)   | 1,179--2,047 MB    |      142.6 |     149.2 |   110.4 |      -4.5% |    **-26.0%** |

### Chrome CPU% (avg)

| Quartile        | HL RSS Range       |   Headless |   Headful |   Shell |   HL vs HF |   Shell vs HF |
|-----------------|--------------------|-----------:|----------:|--------:|-----------:|--------------:|
| Q1 (lightest)   | 848--1,002 MB      |       16.0 |      18.0 |    13.0 |     -11.0% |    **-27.7%** |
| Q2              | 1,002--1,080 MB    |       39.0 |      42.3 |    35.2 |      -7.9% |    **-16.9%** |
| Q3              | 1,080--1,179 MB    |       65.2 |      68.0 |    57.1 |      -4.2% |    **-16.0%** |
| Q4 (heaviest)   | 1,179--2,047 MB    |      110.5 |     113.3 |    88.2 |      -2.4% |    **-22.1%** |

### Chrome CPU% (peak)

| Quartile        | HL RSS Range       |   Headless |   Headful |   Shell |   HL vs HF |   Shell vs HF |
|-----------------|--------------------|-----------:|----------:|--------:|-----------:|--------------:|
| Q1 (lightest)   | 848--1,002 MB      |       61.6 |      67.0 |    56.3 |      -8.0% |    **-15.9%** |
| Q2              | 1,002--1,080 MB    |      134.0 |     141.3 |   125.1 |      -5.2% |    **-11.5%** |
| Q3              | 1,080--1,179 MB    |      184.6 |     188.5 |   170.8 |      -2.1% |     **-9.4%** |
| Q4 (heaviest)   | 1,179--2,047 MB    |      249.7 |     249.2 |   207.3 |      +0.2% |    **-16.8%** |

#### Timing Metrics

### Wall-clock Load Time (ms)

| Quartile        | HL RSS Range       |   Headless |   Headful |     Shell |   HL vs HF |   Shell vs HF |
|-----------------|--------------------|-----------:|----------:|----------:|-----------:|--------------:|
| Q1 (lightest)   | 848--1,002 MB      |    3,280.6 |   3,293.3 |   3,358.7 |      -0.4% |        +2.0%  |
| Q2              | 1,002--1,080 MB    |    3,373.3 |   3,385.8 |   3,487.7 |      -0.4% |        +3.0%  |
| Q3              | 1,080--1,179 MB    |    3,180.3 |   3,245.9 |   3,298.8 |      -2.0% |        +1.6%  |
| Q4 (heaviest)   | 1,179--2,047 MB    |    3,150.5 |   3,169.7 |   3,175.8 |      -0.6% |        +0.2%  |

### TTFB (ms)

| Quartile        | HL RSS Range       |   Headless |   Headful |   Shell |   HL vs HF |   Shell vs HF |
|-----------------|--------------------|-----------:|----------:|--------:|-----------:|--------------:|
| Q1 (lightest)   | 848--1,002 MB      |      630.2 |     632.2 |   667.3 |      -0.3% |     **+5.6%** |
| Q2              | 1,002--1,080 MB    |      599.9 |     594.5 |   614.7 |      +0.9% |        +3.4%  |
| Q3              | 1,080--1,179 MB    |      504.0 |     552.4 |   565.5 |      -8.8% |        +2.4%  |
| Q4 (heaviest)   | 1,179--2,047 MB    |      459.5 |     466.4 |   514.3 |      -1.5% |    **+10.3%** |

### Connect (ms)

| Quartile        | HL RSS Range       |   Headless |   Headful |   Shell |   HL vs HF |   Shell vs HF |
|-----------------|--------------------|-----------:|----------:|--------:|-----------:|--------------:|
| Q1 (lightest)   | 848--1,002 MB      |      224.3 |     223.4 |   256.0 |      +0.4% |    **+14.6%** |
| Q2              | 1,002--1,080 MB    |      125.7 |     126.2 |   155.6 |      -0.4% |    **+23.3%** |
| Q3              | 1,080--1,179 MB    |      100.4 |     102.0 |   132.2 |      -1.6% |    **+29.6%** |
| Q4 (heaviest)   | 1,179--2,047 MB    |       75.3 |      76.5 |   112.5 |      -1.6% |    **+47.1%** |

### DOM Content Loaded (ms)

| Quartile        | HL RSS Range       |   Headless |   Headful |     Shell |   HL vs HF |   Shell vs HF |
|-----------------|--------------------|-----------:|----------:|----------:|-----------:|--------------:|
| Q1 (lightest)   | 848--1,002 MB      |    1,266.1 |   1,284.5 |   1,331.1 |      -1.4% |        +3.6%  |
| Q2              | 1,002--1,080 MB    |    1,346.7 |   1,359.0 |   1,451.2 |      -0.9% |     **+6.8%** |
| Q3              | 1,080--1,179 MB    |    1,175.7 |   1,240.1 |   1,289.4 |      -5.2% |        +4.0%  |
| Q4 (heaviest)   | 1,179--2,047 MB    |    1,133.1 |   1,149.5 |   1,157.2 |      -1.4% |        +0.7%  |

---

## Error and Compatibility

### Error Summary (Fresh Mode)

| Category                     |   Headless |   Headful |   Headless-Shell |
|------------------------------|-----------:|----------:|-----------------:|
| Total errors                 |         33 |        33 |               59 |
| Timeouts                     |         27 |        36 |               32 |
| `ERR_HTTP2_PROTOCOL_ERROR`   |          0 |         0 |             **36** |
| `ERR_CERT_*`                 |         21 |        19 |               19 |
| `ERR_ABORTED`                |          4 |         4 |                4 |
| Other                        |          8 |        10 |                0 |

### HTTP Status Distribution (Fresh Mode)

| Status             |   Headless |   Headful |   Headless-Shell |
|--------------------|-----------:|----------:|-----------------:|
| 200 OK             |      1,716 |     1,713 |            1,619 |
| 403 Forbidden      |         30 |        31 |             **95** |
| 404 Not Found      |         49 |        49 |               53 |
| 0 (no response)    |         60 |        69 |             **91** |
| Other              |         75 |        68 |               72 |

### Content Divergence

| Comparison                      |   URLs Compared |   >50% Divergent |   >20% Divergent |
|---------------------------------|----------------:|-----------------:|-----------------:|
| Headless vs Headful             |             940 |         8 (0.9%) |       30 (3.2%)  |
| Headless vs Headless-Shell      |             920 |      **58 (6.3%)** |    **95 (10.3%)** |

---

## Fresh vs Reuse Growth

| Metric                   |   Fresh (mean) |   Reuse (mean) |   Growth Factor |
|--------------------------|---------------:|---------------:|----------------:|
| Headless Active (MB)     |            563 |          3,650 |            6.5x |
| Headful Active (MB)      |            591 |          4,034 |            6.8x |
| Shell Active (MB)        |            436 |          3,809 |            8.7x |
