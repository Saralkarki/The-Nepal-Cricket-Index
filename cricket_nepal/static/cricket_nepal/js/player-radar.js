(() => {
    const namespace = "http://www.w3.org/2000/svg";
    const centerX = 250;
    const centerY = 200;
    const radius = 125;
    const chartWidth = 500;
    const chartHeight = 400;

    function createSvgElement(name, attributes = {}) {
        const element = document.createElementNS(namespace, name);
        for (const [key, value] of Object.entries(attributes)) {
            element.setAttribute(key, value);
        }
        return element;
    }

    function pointFor(index, value, count) {
        const angle = -Math.PI / 2 + (2 * Math.PI * index) / count;
        const scaledRadius = (value / 100) * radius;
        return {
            x: centerX + Math.cos(angle) * scaledRadius,
            y: centerY + Math.sin(angle) * scaledRadius,
            angle,
        };
    }

    function renderChart(container) {
        const dataElement = document.getElementById(container.dataset.chartData);
        if (!dataElement) {
            return;
        }

        const chart = JSON.parse(dataElement.textContent);
        const axes = chart.axes;
        if (!axes.length) {
            return;
        }

        const color = container.dataset.color === "green"
            ? { stroke: "#315b49", fill: "#315b49" }
            : { stroke: "#183438", fill: "#183438" };
        const svg = createSvgElement("svg", {
            viewBox: `0 0 ${chartWidth} ${chartHeight}`,
            role: "presentation",
            focusable: "false",
            "aria-hidden": "true",
        });

        for (let level = 20; level <= 100; level += 20) {
            const ringPoints = axes.map((_, index) => {
                const point = pointFor(index, level, axes.length);
                return `${point.x},${point.y}`;
            });
            svg.append(
                createSvgElement("polygon", {
                    points: ringPoints.join(" "),
                    class: "radar-grid-ring",
                }),
            );
        }

        axes.forEach((axis, index) => {
            const outerPoint = pointFor(index, 100, axes.length);
            svg.append(
                createSvgElement("line", {
                    x1: centerX,
                    y1: centerY,
                    x2: outerPoint.x,
                    y2: outerPoint.y,
                    class: "radar-axis-line",
                }),
            );

            const labelRadius = radius + 34;
            const labelX = centerX + Math.cos(outerPoint.angle) * labelRadius;
            const labelY = centerY + Math.sin(outerPoint.angle) * labelRadius;
            const label = createSvgElement("text", {
                x: labelX,
                y: labelY,
                class: "radar-axis-label",
                "text-anchor": labelX < centerX - 12
                    ? "end"
                    : labelX > centerX + 12
                        ? "start"
                        : "middle",
                "dominant-baseline": labelY < centerY - 12
                    ? "auto"
                    : labelY > centerY + 12
                        ? "hanging"
                        : "middle",
            });
            label.textContent = `${axis.label} ${axis.higher_is_better ? "↑" : "↓"}`;
            const tooltip = createSvgElement("title");
            tooltip.textContent = axis.tooltip;
            label.append(tooltip);
            svg.append(label);
        });

        const points = axes.map((axis, index) => (
            axis.normalized === null
                ? null
                : pointFor(index, axis.normalized, axes.length)
        ));
        const allMetricsAvailable = points.every((point) => point !== null);
        if (allMetricsAvailable) {
            svg.append(
                createSvgElement("polygon", {
                    points: points.map((point) => `${point.x},${point.y}`).join(" "),
                    class: "radar-data-area",
                    stroke: color.stroke,
                    fill: color.fill,
                }),
            );
        } else {
            points.forEach((point, index) => {
                const next = points[(index + 1) % points.length];
                if (point && next) {
                    svg.append(
                        createSvgElement("line", {
                            x1: point.x,
                            y1: point.y,
                            x2: next.x,
                            y2: next.y,
                            class: "radar-data-segment",
                            stroke: color.stroke,
                        }),
                    );
                }
            });
        }

        points.forEach((point, index) => {
            if (!point) {
                return;
            }
            const marker = createSvgElement("circle", {
                cx: point.x,
                cy: point.y,
                r: 4,
                class: "radar-data-point",
                fill: color.stroke,
            });
            const tooltip = createSvgElement("title");
            tooltip.textContent = axes[index].tooltip;
            marker.append(tooltip);
            svg.append(marker);
        });

        container.append(svg);
    }

    document.querySelectorAll("[data-radar-chart]").forEach(renderChart);
})();
