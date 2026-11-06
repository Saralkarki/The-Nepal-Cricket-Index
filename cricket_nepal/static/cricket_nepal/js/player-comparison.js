(() => {
    const root = document.querySelector(".player-comparison-page");
    if (!root) {
        return;
    }

    const cardsContainer = root.querySelector("#comparison-player-cards");
    const addPlayerButton = root.querySelector("#comparison-add-player");
    const status = root.querySelector("#comparison-status");
    const results = root.querySelector("#comparison-results");
    const radarDialog = root.querySelector("#comparison-radar-dialog");
    const radarDialogTitle = root.querySelector("#comparison-radar-dialog-title");
    const radarEnlarged = root.querySelector("#comparison-radar-enlarged");
    const playerOptions = JSON.parse(document.getElementById("comparison-player-options").textContent);
    const cards = [];
    let cardSequence = 0;
    let dataRequest;
    const seriesColors = [
        "#1976d2",
        "#7b2cbf",
        "#2e8b57",
        "#d2691e",
        "#00838f",
        "#c2185b",
        "#5d6d7e",
        "#827717",
    ];

    function colorFor(index) {
        return seriesColors[index % seriesColors.length];
    }

    const battingMetrics = [
        ["Matches", "matches", "integer"],
        ["Innings", "innings", "integer"],
        ["Runs", "runs", "integer"],
        ["Batting Average", "average", "decimal"],
        ["Strike Rate", "strike_rate", "decimal"],
        ["Balls Faced", "balls_faced", "integer"],
        ["Fours", "fours", "integer"],
        ["Sixes", "sixes", "integer"],
        ["Dot-ball Percentage", "dot_ball_percentage", "percent"],
        ["Highest Score", "highest_score", "integer"],
    ];

    const bowlingMetrics = [
        ["Matches", "matches", "integer"],
        ["Innings", "innings", "integer"],
        ["Overs", "overs", "text"],
        ["Runs Conceded", "runs_conceded", "integer"],
        ["Wickets", "wickets", "integer"],
        ["Bowling Average", "average", "decimal"],
        ["Economy", "economy", "decimal"],
        ["Bowling Strike Rate", "strike_rate", "decimal"],
        ["Maidens", "maidens", "integer"],
        ["Dot-ball Percentage", "dot_ball_percentage", "percent"],
        ["Best Bowling Figures", "best_bowling_figures", "text"],
    ];

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) {
            node.className = className;
        }
        if (text !== undefined) {
            node.textContent = text;
        }
        return node;
    }

    function selectedIds(exceptCard) {
        return cards
            .filter((card) => card !== exceptCard && card.player)
            .map((card) => card.player.player_id);
    }

    function setOptions(select, values, placeholder) {
        const selected = select.value;
        select.replaceChildren(new Option(placeholder, ""));
        for (const [value, label] of values) {
            select.add(new Option(label, value));
        }
        select.value = values.some(([value]) => value === selected) ? selected : "";
    }

    function refreshCardOptions(card) {
        const team = card.team.value;
        const season = card.season.value;
        const excluded = new Set(selectedIds(card));
        const eligible = playerOptions.filter(
            (player) => (!team || player.team_name === team)
                && (!season || player.season === season)
                && !excluded.has(player.player_id),
        );
        const uniquePlayers = new Map(eligible.map((player) => [player.player_id, player]));
        card.availablePlayers = uniquePlayers;
        setOptions(
            card.playerSelect,
            [...uniquePlayers.values()].map((player) => [String(player.player_id), player.player_name]),
            uniquePlayers.size ? "Choose a player" : "No available players",
        );
        card.playerSelect.disabled = uniquePlayers.size === 0;
    }

    function selectPlayer(card, player) {
        if (selectedIds(card).includes(player.player_id)) {
            status.textContent = `${player.player_name} is already selected.`;
            refreshCardOptions(card);
            return;
        }
        card.player = player;
        card.playerSelect.value = "";
        card.input.value = "";
        card.suggestions.replaceChildren();
        renderCard(card);
        cards.forEach(refreshCardOptions);
        updateComparison();
    }

    function addCard() {
        const card = { player: null, request: null, timer: null };
        cardSequence += 1;
        card.element = element("article", "comparison-player-card");
        card.heading = element("span", "comparison-player-card-number", `Player ${cardSequence}`);
        card.element.append(card.heading);

        card.chooser = element("div", "comparison-player-chooser");
        function addSelector(label, placeholder) {
            const wrapper = element("label", "comparison-card-filter");
            wrapper.append(element("span", "", label));
            const select = element("select");
            select.setAttribute("aria-label", `${label} for player ${cardSequence}`);
            select.add(new Option(placeholder, ""));
            wrapper.append(select);
            card.chooser.append(wrapper);
            return select;
        }
        card.team = addSelector("NPL team", "All NPL teams");
        card.season = addSelector("Season", "All seasons");
        card.playerSelect = addSelector("Player", "Choose a player");
        const teams = [...new Set(playerOptions.map((player) => player.team_name))]
            .sort((a, b) => a.localeCompare(b));
        const seasons = [...new Set(playerOptions.map((player) => player.season))]
            .sort((a, b) => b.localeCompare(a));
        setOptions(card.team, teams.map((team) => [team, team]), "All NPL teams");
        setOptions(card.season, seasons.map((season) => [season, season]), "All seasons");
        function changeScope() {
            card.request?.abort();
            window.clearTimeout(card.timer);
            card.suggestions.replaceChildren();
            card.input.setAttribute("aria-expanded", "false");
            refreshCardOptions(card);
            if (card.input.value.trim().length >= 2) {
                searchForPlayers(card);
            }
        }
        card.team.addEventListener("change", changeScope);
        card.season.addEventListener("change", changeScope);
        card.playerSelect.addEventListener("change", () => {
            const player = card.availablePlayers.get(Number(card.playerSelect.value));
            if (player) {
                selectPlayer(card, player);
            }
        });

        card.searchLabel = element("label", "comparison-player-search");
        card.searchLabel.append(element("span", "", "Or search by name"));
        card.input = element("input");
        card.input.type = "search";
        card.input.autocomplete = "off";
        card.input.setAttribute("aria-label", `Search for player ${cardSequence}`);
        card.input.setAttribute("aria-expanded", "false");
        card.input.setAttribute("placeholder", "Type a player name");
        card.searchLabel.append(card.input);
        card.suggestions = element("ul", "comparison-player-suggestions");
        card.suggestions.setAttribute("role", "listbox");
        card.searchLabel.append(card.suggestions);
        card.chooser.append(card.searchLabel);
        const removeEmptyButton = element("button", "comparison-remove-empty", "Remove card");
        removeEmptyButton.type = "button";
        removeEmptyButton.addEventListener("click", () => removeCard(card));
        card.chooser.append(removeEmptyButton);
        card.element.append(card.chooser);

        card.selected = element("div", "comparison-selected-player");
        card.element.append(card.selected);

        card.input.addEventListener("input", () => {
            window.clearTimeout(card.timer);
            if (card.request) {
                card.request.abort();
            }
            card.timer = window.setTimeout(() => searchForPlayers(card), 180);
        });

        cardsContainer.insertBefore(card.element, addPlayerButton);
        cards.push(card);
        refreshCardOptions(card);
        renderCard(card);
    }

    function renderCard(card) {
        card.heading.textContent = `Player ${cards.indexOf(card) + 1}`;
        card.chooser.hidden = Boolean(card.player);
        card.selected.replaceChildren();
        if (!card.player) {
            return;
        }

        const avatar = element(
            "span",
            "comparison-player-avatar",
            card.player.player_name
                .split(/\s+/)
                .map((part) => part[0])
                .join("")
                .slice(0, 2)
                .toUpperCase(),
        );
        avatar.setAttribute("aria-hidden", "true");
        const identity = element("div", "comparison-player-identity");
        const nameLink = element("a", "comparison-player-name", card.player.player_name);
        nameLink.href = card.player.profile_url;
        identity.append(nameLink);
        identity.append(element(
            "span",
            "comparison-player-scope",
            `${card.team.value || "All NPL teams"} · ${card.season.value || "All seasons"}`,
        ));

        const controls = element("div", "comparison-player-card-actions");
        const changeButton = element("button", "", "Change");
        changeButton.type = "button";
        changeButton.addEventListener("click", () => {
            card.player = null;
            card.input.value = "";
            renderCard(card);
            cards.forEach(refreshCardOptions);
            card.input.focus();
            updateComparison();
        });
        const removeButton = element("button", "", "Remove");
        removeButton.type = "button";
        removeButton.addEventListener("click", () => removeCard(card));
        controls.append(changeButton, removeButton);
        identity.append(controls);
        const badge = element(
            "span",
            `comparison-player-badge comparison-player-badge-${(cards.indexOf(card) % 4) + 1}`,
            `Player ${cards.indexOf(card) + 1}`,
        );
        card.selected.append(avatar, identity, badge);
    }

    async function searchForPlayers(card) {
        const query = card.input.value.trim();
        card.suggestions.replaceChildren();
        if (query.length < 2) {
            card.input.setAttribute("aria-expanded", "false");
            return;
        }

        card.request = new AbortController();
        const url = new URL(root.dataset.playerSearchUrl, window.location.href);
        url.searchParams.set("q", query);
        try {
            const response = await fetch(url, { signal: card.request.signal });
            if (!response.ok) {
                throw new Error("Player search is unavailable.");
            }
            const payload = await response.json();
            if (query !== card.input.value.trim()) {
                return;
            }
            const excluded = new Set(selectedIds(card));
            const available = card.availablePlayers;
            const matches = payload.players.filter(
                (player) => !excluded.has(player.player_id) && available.has(player.player_id),
            );
            if (matches.length === 0) {
                card.suggestions.append(
                    element("li", "comparison-suggestion-empty", "No available players found."),
                );
            }
            for (const player of matches) {
                const item = element("li");
                const option = element("button", "comparison-player-option", player.player_name);
                option.type = "button";
                option.setAttribute("role", "option");
                option.addEventListener("click", () => {
                    selectPlayer(card, player);
                });
                item.append(option);
                card.suggestions.append(item);
            }
            card.input.setAttribute("aria-expanded", String(matches.length > 0));
        } catch (error) {
            if (error.name !== "AbortError") {
                card.suggestions.replaceChildren(
                    element("li", "comparison-suggestion-empty", "Could not load players. Try again."),
                );
                card.input.setAttribute("aria-expanded", "true");
            }
        }
    }

    function removeCard(card) {
        card.request?.abort();
        window.clearTimeout(card.timer);
        card.element.remove();
        cards.splice(cards.indexOf(card), 1);
        cards.forEach(renderCard);
        cards.forEach(refreshCardOptions);
        updateComparison();
    }

    function formatValue(value, format) {
        if (value === null || value === undefined || value === "") {
            return "—";
        }
        if (format === "decimal") {
            return Number(value).toFixed(2);
        }
        if (format === "percent") {
            return `${Number(value).toFixed(2)}%`;
        }
        if (format === "integer") {
            return new Intl.NumberFormat().format(Number(value));
        }
        return String(value);
    }

    function renderTable(kind, metrics, players) {
        const head = root.querySelector(`#comparison-${kind}-head`);
        const body = root.querySelector(`#comparison-${kind}-body`);
        head.replaceChildren();
        body.replaceChildren();

        const header = element("tr");
        header.append(element("th", "", "Statistic"));
        players.forEach((player, playerIndex) => {
            const cell = element("th", "comparison-table-player-heading");
            const dot = element("span", "comparison-series-dot");
            dot.style.backgroundColor = colorFor(playerIndex);
            dot.setAttribute("aria-hidden", "true");
            const link = element("a", "", player.player_name);
            link.href = player.profile_url;
            cell.append(dot, link);
            header.append(cell);
        });
        head.append(header);

        for (const [label, key, format] of metrics) {
            const row = element("tr");
            row.append(element("th", "", label));
            for (const player of players) {
                const stats = player[kind];
                row.append(
                    element(
                        "td",
                        stats ? "" : "comparison-no-data",
                        stats ? formatValue(stats[key], format) : "No data",
                    ),
                );
            }
            body.append(row);
        }
    }

    function chartPoint(index, value, count) {
        const angle = -Math.PI / 2 + (2 * Math.PI * index) / count;
        const radius = (value / 100) * 125;
        return {
            x: 250 + Math.cos(angle) * radius,
            y: 200 + Math.sin(angle) * radius,
            angle,
        };
    }

    function svgNode(name, attributes = {}) {
        const node = document.createElementNS("http://www.w3.org/2000/svg", name);
        for (const [key, value] of Object.entries(attributes)) {
            node.setAttribute(key, value);
        }
        return node;
    }

    function renderChart(kind, players) {
        const container = root.querySelector(`#comparison-${kind}-chart`);
        container.replaceChildren();
        const axes = players[0]?.radar[kind].axes ?? [];
        if (
            !axes.length
            || !players.some((player) => player.radar[kind].axes.some(
                (axis) => axis.normalized !== null,
            ))
        ) {
            container.append(
                element(
                    "p",
                    "comparison-chart-empty",
                    players.length
                        ? "No records for the selected players."
                        : "Select players to view this chart.",
                ),
            );
            return;
        }

        const svg = svgNode("svg", {
            viewBox: "0 0 500 400",
            role: "img",
            "aria-label": `${kind === "batting" ? "Batting" : "Bowling"} radar comparison`,
        });
        for (let level = 20; level <= 100; level += 20) {
            const points = axes.map((_, index) => {
                const point = chartPoint(index, level, axes.length);
                return `${point.x},${point.y}`;
            });
            svg.append(
                svgNode("polygon", {
                    points: points.join(" "),
                    class: "radar-grid-ring",
                }),
            );
        }

        axes.forEach((axis, index) => {
            const point = chartPoint(index, 100, axes.length);
            svg.append(
                svgNode("line", {
                    x1: 250,
                    y1: 200,
                    x2: point.x,
                    y2: point.y,
                    class: "radar-axis-line",
                }),
            );
            const labelRadius = 160;
            const label = svgNode("text", {
                x: 250 + Math.cos(point.angle) * labelRadius,
                y: 200 + Math.sin(point.angle) * labelRadius,
                class: "radar-axis-label",
                "text-anchor": "middle",
            });
            label.textContent = axis.label;
            svg.append(label);
        });

        const legend = element("ul", "comparison-chart-legend");
        players.forEach((player, playerIndex) => {
            const color = colorFor(playerIndex);
            const seriesAxes = player.radar[kind].axes;
            const points = seriesAxes.map((axis, index) => (
                axis.normalized === null
                    ? null
                    : chartPoint(index, axis.normalized, seriesAxes.length)
            ));

            if (points.every(Boolean)) {
                svg.append(
                    svgNode("polygon", {
                        points: points.map((point) => `${point.x},${point.y}`).join(" "),
                        class: "comparison-radar-series",
                        stroke: color,
                        fill: color,
                    }),
                );
            } else {
                points.forEach((point, index) => {
                    const next = points[(index + 1) % points.length];
                    if (point && next) {
                        svg.append(
                            svgNode("line", {
                                x1: point.x,
                                y1: point.y,
                                x2: next.x,
                                y2: next.y,
                                class: "comparison-radar-segment",
                                stroke: color,
                            }),
                        );
                    }
                });
            }

            points.forEach((point, index) => {
                if (!point) {
                    return;
                }
                const marker = svgNode("circle", {
                    cx: point.x,
                    cy: point.y,
                    r: 4,
                    class: "comparison-radar-point",
                    fill: color,
                });
                const tooltip = svgNode("title");
                tooltip.textContent = `${seriesAxes[index].label}: ${seriesAxes[index].actual}`;
                marker.append(tooltip);
                svg.append(marker);
            });

            const item = element("li");
            const swatch = element("span", "comparison-legend-swatch");
            swatch.style.backgroundColor = color;
            swatch.setAttribute("aria-hidden", "true");
            const link = element("a", "", player.player_name);
            link.href = player.profile_url;
            item.append(swatch, link);
            legend.append(item);
        });

        const enlargeButton = element("button", "comparison-chart-enlarge");
        enlargeButton.type = "button";
        const label = `${kind === "batting" ? "Batting" : "Bowling"} radar comparison`;
        enlargeButton.setAttribute("aria-label", `Enlarge ${label}`);
        enlargeButton.append(svg, element("span", "comparison-chart-enlarge-label", "Click to enlarge"));
        enlargeButton.addEventListener("click", () => {
            radarDialogTitle.textContent = label;
            radarEnlarged.replaceChildren(svg.cloneNode(true), legend.cloneNode(true));
            radarDialog.showModal();
        });
        container.append(enlargeButton, legend);
    }

    async function updateComparison() {
        if (radarDialog.open) {
            radarDialog.close();
        }
        const selectedCards = cards.filter((card) => card.player);
        if (dataRequest) {
            dataRequest.abort();
        }
        dataRequest = new AbortController();
        status.textContent = selectedCards.length
            ? "Loading comparison data…"
            : "Select players to compare their statistics.";
        results.hidden = true;
        try {
            if (selectedCards.length === 0) {
                status.textContent = "Select players to compare their statistics.";
                return;
            }
            const signal = dataRequest.signal;
            const players = await Promise.all(selectedCards.map(async (card) => {
                const url = new URL(root.dataset.comparisonDataUrl, window.location.href);
                url.searchParams.set("player", card.player.player_id);
                url.searchParams.set("tournament", "Nepal Premier League");
                url.searchParams.set("team", card.team.value);
                url.searchParams.set("season", card.season.value);
                url.searchParams.set("scope", "matches");
                const response = await fetch(url, { signal });
                const payload = await response.json();
                if (!response.ok) {
                    throw new Error(payload.error || "Comparison data is unavailable.");
                }
                return payload.players[0];
            }));
            if (signal.aborted) {
                return;
            }
            renderTable("batting", battingMetrics, players);
            renderTable("bowling", bowlingMetrics, players);
            renderChart("batting", players);
            renderChart("bowling", players);
            results.hidden = false;
            const missing = players.filter(
                (player) => !player.batting && !player.bowling,
            );
            status.textContent = missing.length
                ? `${players.length} players selected. ${missing.map((player) => player.player_name).join(", ")} have no records for this selection.`
                : `${players.length} players compared.`;
        } catch (error) {
            if (error.name !== "AbortError") {
                status.textContent = error.message || "Could not load comparison data.";
            }
        }
    }

    addPlayerButton.addEventListener("click", () => {
        addCard();
        cards[cards.length - 1].input.focus();
    });
    root.querySelector("#comparison-radar-close").addEventListener("click", () => {
        radarDialog.close();
    });

    addPlayerButton.className = "comparison-add-player-card";
    addPlayerButton.replaceChildren(
        element("span", "comparison-add-player-icon", "+"),
        element("span", "", "Add Player"),
    );
    cardsContainer.append(addPlayerButton);
    addCard();
    addCard();
})();
