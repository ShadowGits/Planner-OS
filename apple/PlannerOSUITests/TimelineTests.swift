import XCTest

/// The timeline: one scroll across days, midnight to midnight, with swipes and drags.
@MainActor
final class TimelineTests: PlannerScreenTests {
    private func clock(_ id: String, on date: String) throws -> String? {
        (try server.ownTask(id, on: date)?["start_time"] as? String).map { String($0.prefix(5)) }
    }

    // MARK: The scroll and the days

    func testOpensAtNow() throws {
        launch(at: nil)
        waitForTile(today, "it opens today")
        let now = app.descendants(matching: .any).matching(NSPredicate(format: "label BEGINSWITH 'Now, '")).firstMatch
        XCTAssertTrue(now.waitForExistence(timeout: 5), "no now bar")
        let area = app.scrollViews["timeline"].firstMatch.frame
        XCTAssertTrue(now.frame.midY > area.minY && now.frame.midY < area.maxY, "now is not on screen")
    }

    func testScrollsAcrossDaysAndTheTileFollows() throws {
        for offset in -1...3 { try server.create("Task on day \(offset)", date: day(offset), time: "09:00", minutes: 60) }
        launch()
        waitForTile(today, "at the start")
        for offset in [1, 2] {
            var turns = 0
            while !tile.label.contains(tileWords(day(offset))), turns < 14 {
                scroll(by: 420)
                turns += 1
            }
            waitForTile(day(offset), "scrolled forward")
        }
        var turns = 0
        while !tile.label.contains(tileWords(day(-1))), turns < 36 {
            scroll(by: -420)
            turns += 1
        }
        waitForTile(day(-1), "scrolled back past today")
    }

    func testEachDayStartsUnderItsHeader() throws {
        try server.create("Late", date: today, time: "23:00", minutes: 60)
        try server.create("Early", date: day(1), time: "00:30", minutes: 60)
        launch(at: "23:30")
        let line = header(day(1))
        XCTAssertTrue(line.waitForExistence(timeout: 5), "no header where tomorrow starts")
        XCTAssertTrue(body("Early").waitForExistence(timeout: 5))
        XCTAssertLessThan(body("Late").frame.maxY, line.frame.minY, "today's last task is not above the line")
        XCTAssertGreaterThan(body("Early").frame.minY, line.frame.maxY, "tomorrow's first task is not below it")
    }

    func testHalfPastOneShowsOnceUnderTheNextDate() throws {
        let owl = try server.create("Night owl", date: day(1), time: "01:30", minutes: 60)
        XCTAssertNotNil(try server.task(owl, on: today), "the server no longer lists it on both days: this test proves nothing")
        launch(at: "23:30")
        XCTAssertTrue(body("Night owl").waitForExistence(timeout: 5))
        XCTAssertEqual(app.buttons.matching(NSPredicate(format: "label == 'Night owl'")).count, 1, "it shows twice")
        XCTAssertGreaterThan(body("Night owl").frame.minY, header(day(1)).frame.maxY, "it is not under the next date")
    }

    func testEveryHourIsFiftyPoints() throws {
        try server.create("Nine", date: today, time: "09:00", minutes: 60)
        try server.create("Ten thirty", date: today, time: "10:30", minutes: 30)
        try server.create("Two", date: today, time: "14:00", minutes: 120)
        launch()
        XCTAssertTrue(body("Two").waitForExistence(timeout: 5))
        let nine = body("Nine").frame
        XCTAssertEqual(body("Ten thirty").frame.minY - nine.minY, 75, accuracy: 1.5, "an hour and a half")
        XCTAssertEqual(body("Two").frame.minY - nine.minY, 250, accuracy: 1.5, "five hours, three and a half of them empty")
        XCTAssertEqual(nine.height, 50, accuracy: 1.5, "an hour's task")
        XCTAssertEqual(body("Two").frame.height, 100, accuracy: 1.5, "two hours' task")
    }

    func testOverlappingTasksSitSideBySide() throws {
        try server.create("Side left", date: today, time: "10:00", minutes: 60)
        try server.create("Side right", date: today, time: "10:00", minutes: 60)
        launch()
        XCTAssertTrue(body("Side right").waitForExistence(timeout: 5))
        XCTAssertEqual(body("Side left").frame.minY, body("Side right").frame.minY, accuracy: 1.5)
        XCTAssertLessThanOrEqual(body("Side left").frame.maxX, body("Side right").frame.minX + 1, "they cover each other")
    }

    func testUntimedTasksAreListedUnderTheirHeader() throws {
        try server.create("Any time", date: today)
        try server.create("Just after midnight", date: today, time: "00:30")
        launch(at: "00:00")
        XCTAssertTrue(body("Any time").waitForExistence(timeout: 5))
        XCTAssertGreaterThan(body("Any time").frame.minY, header(today).frame.maxY - 1)
        XCTAssertLessThan(body("Any time").frame.maxY, body("Just after midnight").frame.minY)
        XCTAssertEqual(body("Any time").frame.height, 44, accuracy: 1.5, "the list is not compact")
    }

    func testNoWeekStripAndSidewaysDoesNotChangeTheDay() throws {
        launch()
        waitForTile(today, "at the start")
        for offset in [-1, 1] {
            XCTAssertFalse(app.buttons[tileWords(day(offset))].exists, "the week strip is still there")
        }
        let area = app.scrollViews["timeline"].firstMatch
        let from = point(area, x: area.frame.width * 0.85, y: area.frame.height * 0.5)
        let to = from.withOffset(CGVector(dx: -area.frame.width * 0.6, dy: 0))
        #if os(macOS)
        from.click(forDuration: 0.02, thenDragTo: to)
        #else
        from.press(forDuration: 0.02, thenDragTo: to)
        #endif
        settle()
        waitForTile(today, "after a sideways swipe")
    }

    func testNowComesBack() throws {
        launch(at: nil)
        for _ in 0..<6 { scroll(by: 420) }
        XCTAssertFalse(tile.label.contains(tileWords(today)), "it never scrolled away")
        press(app.buttons["Now"].firstMatch)
        waitForTile(today, "after Now")
    }

    func testScrollingFromOnTopOfATaskScrolls() throws {
        let id = try server.create("Long block", date: today, time: "09:00", minutes: 300)
        launch(at: "11:00")
        let task = body("Long block")
        XCTAssertTrue(task.waitForExistence(timeout: 5))
        let before = task.frame.minY
        #if os(macOS)
        task.scroll(byDeltaX: 0, deltaY: -90)
        #else
        let from = point(task, x: 70, y: task.frame.height - 70)
        from.press(forDuration: 0.02, thenDragTo: from.withOffset(CGVector(dx: 0, dy: -120)))
        #endif
        settle()
        XCTAssertLessThan(task.frame.minY, before - 30, "the list did not scroll")
        XCTAssertFalse(editorButton.exists, "scrolling opened the editor")
        XCTAssertEqual(try clock(id, on: today), "09:00", "scrolling moved the task")
    }

    func testFitGivesAnUntimedTaskATime() throws {
        let date = today
        let id = try server.create("Loose end", date: date)
        launch()
        let fit = app.buttons["Find a time for 1 loose task"].firstMatch
        XCTAssertTrue(fit.waitForExistence(timeout: 5), "no Fit")
        press(fit)
        // Late at night there may be no room left today, and then the server says so.
        let toast = app.staticTexts.matching(NSPredicate(
            // A text's words are its label on the iPhone and its value on the Mac.
            format: "label CONTAINS[c] 'Loose end' OR label CONTAINS[c] 'room' OR label CONTAINS[c] 'not fit' OR value CONTAINS[c] 'Loose end' OR value CONTAINS[c] 'room' OR value CONTAINS[c] 'not fit'")).firstMatch
        eventually("Fit answered") { try clock(id, on: date) != nil || toast.exists }
    }

    func testListViewLeavesTheNextMorningOut() throws {
        try server.create("Night owl", date: day(1), time: "01:30")
        try server.create("Breakfast", date: today, time: "09:00")
        launch()
        XCTAssertTrue(body("Breakfast").waitForExistence(timeout: 5))
        showList()
        XCTAssertTrue(body("Breakfast").waitForExistence(timeout: 5))
        XCTAssertFalse(body("Night owl").exists, "tomorrow's 01:30 is in today's list")
    }

    // MARK: Swipes

    func testSwipeNextDayKeepsTheTime() throws {
        let id = try server.create("Swipe me", date: today, time: "09:00", minutes: 60)
        launch()
        swipeLeft("Swipe me")
        press(app.buttons["swipe-Next day"].firstMatch)
        eventually("it is tomorrow at 09:00") { try clock(id, on: day(1)) == "09:00" }
        eventually("it is drawn under tomorrow's header") {
            let task = body("Swipe me"), line = header(day(1))
            // Tomorrow is either too far down to be drawn, or it is below that line.
            return !task.exists || (line.exists && task.frame.minY > line.frame.maxY)
        }
        XCTAssertFalse(editorButton.exists, "the swipe opened the editor")
    }

    func testSwipeNextDayOnAnUntimedTask() throws {
        let id = try server.create("Any time", date: today)
        launch(at: "00:00")
        swipeLeft("Any time")
        press(app.buttons["swipe-Next day"].firstMatch)
        eventually("it is tomorrow") { try server.ownTask(id, on: day(1)) != nil }
        XCTAssertNil(try clock(id, on: day(1)), "it was given a time")
    }

    func testSwipeArchiveSendsItToTheInbox() throws {
        let id = try server.create("Swipe me", date: today, time: "09:00", minutes: 60)
        launch()
        swipeLeft("Swipe me")
        press(app.buttons["swipe-Archive"].firstMatch)
        eventually("it is in the Inbox, high, with no date or time") {
            guard let task = try server.inbox().first(where: { $0["id"] as? String == id }) else { return false }
            return task["priority"] as? String == "high" && task["scheduled_date"] is NSNull && task["start_time"] is NSNull
        }
        XCTAssertTrue(gone(body("Swipe me")), "it is still on the timeline")
        activate(app.buttons["Inbox"].firstMatch)
        XCTAssertTrue(app.staticTexts["Swipe me"].waitForExistence(timeout: 6), "the Inbox does not show it")
    }

    func testSwipeDeleteAsksFirst() throws {
        let id = try server.create("Swipe me", date: today, time: "09:00", minutes: 60)
        launch()
        swipeLeft("Swipe me")
        press(app.buttons["swipe-Delete"].firstMatch)
        activate(alertButton("Cancel"))
        settle()
        XCTAssertNotNil(try server.ownTask(id, on: today), "Cancel deleted it")
        swipeLeft("Swipe me")
        press(app.buttons["swipe-Delete"].firstMatch)
        activate(alertButton("Delete"))
        eventually("it is deleted") { try server.ownTask(id, on: today) == nil }
        XCTAssertTrue(gone(body("Swipe me")))
    }

    func testDeletingAHabitSkipsThatDayOnly() throws {
        try server.habit("Stretch", time: "09:00", minutes: 60, from: today)
        launch()
        swipeLeft("Stretch")
        XCTAssertFalse(app.buttons["swipe-Archive"].exists, "a habit's day was offered Archive")
        press(app.buttons["swipe-Delete"].firstMatch)
        activate(alertButton("Skip"))
        eventually("today's is skipped") { try !server.day(today).contains { $0["title"] as? String == "Stretch" } }
        XCTAssertTrue(try server.day(day(1)).contains { $0["title"] as? String == "Stretch" }, "tomorrow's went too")
    }

    func testSwipeOnASideBySideTask() throws {
        let id = try server.create("Side left", date: today, time: "10:00", minutes: 60)
        let other = try server.create("Side right", date: today, time: "10:00", minutes: 60)
        launch()
        swipeLeft("Side left")
        press(app.buttons["swipe-Next day"].firstMatch)
        eventually("the left one moved") { try clock(id, on: day(1)) == "10:00" }
        XCTAssertEqual(try clock(other, on: today), "10:00", "the right one moved too")
    }

    #if os(iOS)
    func testASwipeCanStartOnTheStarWithoutStarring() throws {
        let id = try server.create("Side left", date: today, time: "10:00", minutes: 60)
        try server.create("Side right", date: today, time: "10:00", minutes: 60)
        launch()
        let star = app.buttons["Choose Side left as Top Win"].firstMatch
        XCTAssertTrue(star.waitForExistence(timeout: 5))
        let from = point(star, x: star.frame.width / 2, y: star.frame.height / 2)
        from.press(forDuration: 0.02, thenDragTo: from.withOffset(CGVector(dx: -110, dy: 0)), withVelocity: .default, thenHoldForDuration: 0)
        settle()
        XCTAssertTrue(app.buttons["swipe-Next day"].firstMatch.waitForExistence(timeout: 3), "no swipe from the star")
        XCTAssertEqual(try server.ownTask(id, on: today)?["starred"] as? Bool, false, "the swipe starred it")
    }
    #endif

    func testATapPutsTheSwipeAwayAndTheNextOneOpens() throws {
        try server.create("Swipe me", date: today, time: "09:00", minutes: 60)
        try server.create("Another", date: today, time: "12:00", minutes: 60)
        launch()
        swipeLeft("Swipe me")
        XCTAssertTrue(app.buttons["swipe-Delete"].firstMatch.waitForExistence(timeout: 3), "no buttons")
        open("Another")
        XCTAssertTrue(gone(app.buttons["swipe-Delete"].firstMatch), "the buttons stayed out")
        XCTAssertFalse(editorButton.exists, "the tap that closed the swipe also opened a task")
        open("Another")
        XCTAssertTrue(editorButton.waitForExistence(timeout: 4), "the next tap did not open it")
    }

    // MARK: Hold and drag

    func testHoldAndDragMovesWithinTheDay() throws {
        let id = try server.create("Mover", date: today, time: "09:00", minutes: 60)
        launch()
        holdAndDrag("Mover", by: 100)
        eventually("two hours later") { try clock(id, on: today) == "11:00" }
        XCTAssertFalse(editorButton.exists, "dragging opened the editor")
    }

    func testAShortHoldPicksATaskUp() throws {
        let id = try server.create("Mover", date: today, time: "09:00", minutes: 60)
        launch()
        holdAndDrag("Mover", by: 100, hold: 0.32)
        eventually("two hours later, after only a third of a second's hold") { try clock(id, on: today) == "11:00" }
        XCTAssertFalse(editorButton.exists, "dragging opened the editor")
    }

    #if os(iOS)
    func testASlowTapStillOpensTheTask() throws {
        let id = try server.create("Slow tap", date: today, time: "09:00", minutes: 60)
        launch()
        let task = body("Slow tap")
        XCTAssertTrue(task.waitForExistence(timeout: 5))
        point(task, x: min(60, task.frame.width / 3), y: min(12, task.frame.height / 2)).press(forDuration: 0.35)
        XCTAssertTrue(editorButton.waitForExistence(timeout: 4), "a press a little longer than a tap did not open it")
        XCTAssertEqual(try clock(id, on: today), "09:00", "it moved")
    }
    #endif

    func testDragAcrossMidnightIntoTheNextDay() throws {
        let id = try server.create("Late", date: today, time: "23:00", minutes: 30)
        launch(at: "22:00")
        // An hour to midnight, the header between the days, and an hour and a half.
        holdAndDrag("Late", by: 50 + 10 + 64 + 10 + 75)
        eventually("01:30 on the next date") { try clock(id, on: day(1)) == "01:30" }
        XCTAssertNil(try server.ownTask(id, on: today), "it is still dated today")
        XCTAssertTrue(body("Late").waitForExistence(timeout: 4))
        XCTAssertEqual(app.buttons.matching(NSPredicate(format: "label == 'Late'")).count, 1, "it shows twice")
    }

    func testDragBackAcrossMidnight() throws {
        let id = try server.create("Early", date: day(1), time: "01:30", minutes: 30)
        launch(at: "22:30")
        holdAndDrag("Early", by: -(50 + 10 + 64 + 10 + 75))
        eventually("23:00 the date before") { try clock(id, on: today) == "23:00" }
    }

    func testDraggingAHabitAcrossMidnightMovesThatDayOnly() throws {
        try server.habit("Stretch", time: "23:00", minutes: 30, from: today)
        launch(at: "22:00")
        holdAndDrag("Stretch", by: 50 + 10 + 64 + 10 + 75)
        eventually("tomorrow has the moved one at 01:30 and its own at 23:00") {
            let times = try server.day(day(1)).filter { $0["title"] as? String == "Stretch" }
                .compactMap { ($0["start_time"] as? String).map { String($0.prefix(5)) } }
            return times.sorted() == ["01:30", "23:00"]
        }
        XCTAssertFalse(try server.day(today).contains { $0["title"] as? String == "Stretch" }, "it is still on today")
    }

    func testHoldingAtTheEdgeScrolls() throws {
        let id = try server.create("Edge", date: today, time: "11:00", minutes: 60)
        launch()
        let area = app.scrollViews["timeline"].firstMatch.frame
        // To just above the bottom bar, and wait there.
        let bar = app.buttons["Timeline"].firstMatch.frame
        let edge = min(area.maxY, bar.minY) - 8
        let drop = edge - (body("Edge").frame.minY + 12)
        holdAndDrag("Edge", by: drop, pause: 1.2)
        eventually("it landed further down than the screen reached") {
            for later in 1...3 where try server.ownTask(id, on: day(later)) != nil { return true }
            guard let time = try clock(id, on: today), let hour = Int(time.prefix(2)) else { return false }
            return CGFloat(hour - 11) * 50 > drop + 50
        }
    }

    func testDroppingOnTheBinAsksFirst() throws {
        let id = try server.create("Bin me", date: today, time: "09:00", minutes: 60)
        launch()
        let task = body("Bin me").frame, bin = app.buttons["Add task"].firstMatch.frame
        holdAndDrag("Bin me", by: bin.midY - (task.minY + 12), dx: bin.midX - (task.minX + min(60, task.width / 3)))
        let cancel = alertButton("Cancel")
        activate(cancel)
        XCTAssertTrue(gone(cancel), "Cancel did not close the question")
        XCTAssertNotNil(try server.ownTask(id, on: today))
        XCTAssertEqual(try clock(id, on: today), "09:00", "it moved as well")
    }
}
