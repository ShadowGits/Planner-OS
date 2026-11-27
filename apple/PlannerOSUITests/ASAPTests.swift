import XCTest

@MainActor
final class ASAPTests: PlannerScreenTests {
    func testASAPStaysPinnedAcrossDaysUntilClosed() throws {
        _ = try server.send("POST", "/v2/day/asap", ["title": "Urgent fixture"])
        launch()
        let close = app.buttons["Close ASAP: Urgent fixture"].firstMatch
        XCTAssertTrue(close.waitForExistence(timeout: 8))
        for _ in 0..<6 { scroll(by: 420) }
        XCTAssertFalse(tile.label.contains(tileWords(today)))
        XCTAssertTrue(close.isHittable, "ASAP scrolled away with the day")
        activate(close)
        eventually("the closed ASAP item disappears") { !close.exists }
    }
}
