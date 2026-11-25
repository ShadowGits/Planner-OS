import XCTest

/// What the timeline does besides scrolling and moving tasks. Each of these was
/// once lost in a rewrite with nothing to notice; do not delete one unasked.
@MainActor
final class KeptFeatureTests: PlannerScreenTests {
    private func text(containing words: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS %@ OR value CONTAINS %@", words, words)).firstMatch
    }

    private func slot(_ free: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Add a task at' AND label ENDSWITH %@", ", \(free) free")).firstMatch
    }

    private func shot(_ name: String) {
        #if os(iOS)
        // Not on the Mac, where it would be the user's own screen.
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
        #endif
    }

    private func visible(_ element: XCUIElement) -> Bool {
        guard element.exists else { return false }
        let area = app.scrollViews["timeline"].firstMatch.frame
        return element.frame.minY >= area.minY - 2 && element.frame.minY < area.maxY - 90
    }

    private func addFromSlot(_ free: String, named title: String, expecting time: String) throws {
        let gap = slot(free)
        XCTAssertTrue(gap.waitForExistence(timeout: 6), "no slot of \(free)")
        press(gap, x: 24, y: min(14, gap.frame.height / 2))
        let field = app.textFields.firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 5), "the slot did not open a new task")
        activate(field)
        field.typeText(title)
        activate(app.buttons["Add"].firstMatch)
        eventually("\(title) saved at \(time)") {
            try server.day(today).contains { $0["title"] as? String == title && ($0["start_time"] as? String)?.hasPrefix(time) == true }
        }
    }

    func testFreeHourSuggestsAndAddsAtItsStart() throws {
        try server.create("Before", date: today, time: "09:00", minutes: 60)
        try server.create("After", date: today, time: "11:00", minutes: 60)
        launch()
        XCTAssertTrue(slot("1h").waitForExistence(timeout: 6), "no free hour")
        shot("slot-hour")
        try addFromSlot("1h", named: "Fitted in", expecting: "10:00")
    }

    func testLongWindowOffersAddTask() throws {
        try server.create("Before", date: today, time: "09:00", minutes: 60)
        try server.create("After", date: today, time: "14:00", minutes: 60)
        launch()
        XCTAssertTrue(slot("4h").waitForExistence(timeout: 6), "no window")
        shot("slot-window")
        try addFromSlot("4h", named: "In the window", expecting: "10:00")
    }

    func testShortGapStillTakesTheTap() throws {
        try server.create("Before", date: today, time: "09:00", minutes: 62)
        try server.create("After", date: today, time: "10:30", minutes: 60)
        launch()
        try addFromSlot("28m", named: "Squeezed in", expecting: "10:05")
    }

    func testEmptyDaySaysSo() throws {
        launch(at: nil)
        let words = text(containing: "Nothing planned")
        XCTAssertTrue(words.waitForExistence(timeout: 6))
        // Every empty day says it, so any of them in view will do.
        let each = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label == %@ OR value == %@", "Nothing planned", "Nothing planned"))
        eventually("it is on screen where the timeline opens") { each.allElementsBoundByIndex.contains { visible($0) } }
        shot("empty-day")
    }

    func testDayWithOnlyUntimedSaysSo() throws {
        try server.create("Whenever", date: today)
        launch(at: nil)
        let words = text(containing: "Nothing at a set time")
        XCTAssertTrue(words.waitForExistence(timeout: 6))
        eventually("it is on screen where the timeline opens") { visible(words) }
    }

    func testUntimedTaskHasItsMenu() throws {
        let id = try server.create("Whenever", date: today)
        launch(at: "01:30")
        let row = body("Whenever")
        XCTAssertTrue(row.waitForExistence(timeout: 6))
        #if os(macOS)
        row.rightClick()
        let done = app.menuItems["Mark done"].firstMatch
        #else
        row.press(forDuration: 1)
        let done = alertButton("Mark done")
        #endif
        XCTAssertTrue(done.waitForExistence(timeout: 4), "no Mark done")
        shot("untimed-menu")
        activate(done)
        eventually("marked done") { try server.task(id, on: today)?["completed"] as? Bool == true
            || (try server.task(id, on: today)?["status"] as? String).map { ["done", "completed"].contains($0) } == true
            || app.buttons["Reopen Whenever"].exists }
    }

    func testShortAndNarrowTasksSayWhenAndHowLong() throws {
        try server.create("Half hour", date: today, time: "08:00", minutes: 30)
        try server.create("Ten minutes", date: today, time: "09:00", minutes: 10)
        try server.create("Left side", date: today, time: "10:00", minutes: 60)
        try server.create("Right side", date: today, time: "10:00", minutes: 60)
        try server.create("Two hours", date: today, time: "11:30", minutes: 120)
        launch()
        let half = body("Half hour")
        XCTAssertTrue(half.waitForExistence(timeout: 6))
        XCTAssertTrue((half.value as? String)?.contains("30 min") == true, "no length: \(String(describing: half.value))")
        shot("times")
    }

    func testTopWinsStayPinnedWhileTheDayScrolls() throws {
        let id = try server.create("Big one", date: today, time: "09:00", minutes: 60)
        try server.send("PATCH", "/v2/day/tasks/\(id)", ["starred": true])
        launch()
        let chip = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Top Win Big one'")).firstMatch
        XCTAssertTrue(chip.waitForExistence(timeout: 6), "no Top Wins bar")
        shot("wins-morning")
        let place = chip.frame.minY
        scroll(by: 300)
        waitForTile(today, "still today")
        XCTAssertEqual(chip.frame.minY, place, accuracy: 1, "Top Wins moved with the scroll")
        shot("wins-scrolled")
        activate(chip)
        eventually("the chip goes to its task") { visible(body("Big one")) }
        XCTAssertFalse(editorButton.exists, "the chip opened the editor")
    }

    func testTopWinInTheListScrollsToIt() throws {
        for hour in 1...16 { try server.create("Row \(hour)", date: today, time: String(format: "%02d:00", hour)) }
        let id = try server.create("Last one", date: today, time: "20:00")
        try server.send("PATCH", "/v2/day/tasks/\(id)", ["starred": true])
        launch()
        showList()
        let chip = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Top Win Last one'")).firstMatch
        XCTAssertTrue(chip.waitForExistence(timeout: 6), "no Top Wins in the list")
        activate(chip)
        settle(1)
        let bar = app.buttons["Inbox"].firstMatch.frame.minY
        XCTAssertLessThanOrEqual(body("Last one").frame.maxY, bar, "the list left it behind the bottom bar")
        XCTAssertFalse(editorButton.exists, "the chip opened the editor")
        shot("wins-list")
    }

    func testNowGoesToTheTaskNext() throws {
        let format = DateFormatter()
        format.timeZone = TimeZone(identifier: "Asia/Kolkata")
        format.locale = Locale(identifier: "en_US_POSIX")
        format.dateFormat = "HH:mm"
        let parts = format.string(from: Date()).split(separator: ":").compactMap { Int($0) }
        let now = parts[0] * 60 + parts[1]
        try XCTSkipIf(now >= 23 * 60 + 50, "no room left today for a next task")
        let next = min(now + 240, 23 * 60 + 55)
        try server.create("Next up", date: today, time: String(format: "%02d:%02d", next / 60, next % 60), minutes: 5)
        launch(at: now > 12 * 60 ? "02:00" : "21:00")
        activate(app.buttons["Now"].firstMatch)
        eventually("Now shows the next task") { visible(body("Next up")) }
    }

    #if os(iOS)
    func testPickedDayOpensAtItsFirstTask() throws {
        let format = DateFormatter()
        format.timeZone = TimeZone(identifier: "UTC")
        format.locale = Locale(identifier: "en_US_POSIX")
        format.dateFormat = "yyyy-MM-dd"
        // The next day if this month still has one, else the day before.
        let picked = day(1).prefix(7) == today.prefix(7) ? day(1) : day(-1)
        try server.create("First thing", date: picked, time: "15:00", minutes: 60)
        launch(at: "02:00")
        activate(tile)
        let date = format.date(from: picked)!
        format.dateFormat = "d MMMM"
        let british = format.string(from: date)
        format.dateFormat = "MMMM d"
        let american = format.string(from: date)
        let cell = app.buttons.matching(NSPredicate(format: "label ENDSWITH %@ OR label ENDSWITH %@", british, american)).firstMatch
        XCTAssertTrue(cell.waitForExistence(timeout: 5), "no \(american) in the picker")
        activate(cell)
        activate(app.buttons["Go"].firstMatch)
        eventually("it opens at the first task") { visible(body("First thing")) }
    }

    func testPullingFromTheTopRefreshes() throws {
        launch()
        try server.create("From elsewhere", date: today, time: "09:30", minutes: 60)
        let from = point(tile, x: 30, y: 25)
        from.press(forDuration: 0.02, thenDragTo: from.withOffset(CGVector(dx: 0, dy: 190)))
        XCTAssertTrue(body("From elsewhere").waitForExistence(timeout: 5), "the pull did not refresh")
        XCTAssertFalse(app.buttons["Go"].exists, "the pull opened the date picker")
    }

    func testPullingTheListRefreshes() throws {
        try server.create("Already here", date: today, time: "09:00")
        launch()
        showList()
        XCTAssertTrue(body("Already here").waitForExistence(timeout: 5))
        try server.create("From elsewhere", date: today, time: "09:30")
        let from = point(body("Already here"), x: 40, y: 10)
        from.press(forDuration: 0.02, thenDragTo: from.withOffset(CGVector(dx: 0, dy: 420)))
        XCTAssertTrue(body("From elsewhere").waitForExistence(timeout: 5), "the pull did not refresh")
    }

    private func tapStatusBar() {
        // The system's, so a tap through the app's own window never reaches it.
        let home = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        point(home, x: 64, y: 28).tap()
    }

    func testStatusBarGoesToTheTopOfTheDay() throws {
        launch(at: "15:00")
        tapStatusBar()
        eventually("the day's header is on screen") { visible(header(today)) }
        waitForTile(today, "and not two weeks back")
    }

    func testStatusBarStillWorksWithTopWins() throws {
        let id = try server.create("Big one", date: today, time: "09:00")
        try server.send("PATCH", "/v2/day/tasks/\(id)", ["starred": true])
        launch(at: "15:00")
        tapStatusBar()
        eventually("the day's header is on screen") { visible(header(today)) }
        waitForTile(today, "and not two weeks back")
    }
    #endif
}
