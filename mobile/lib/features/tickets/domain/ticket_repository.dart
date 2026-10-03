import 'ticket.dart';

/// UI depends on this interface only.
/// Mock now -> ApiTicketRepository (POST /tickets, GET /tickets/mine) later.
abstract class TicketRepository {
  /// Throws [NotFoundFailure] if the device does not exist.
  Future<Ticket> createTicket(NewTicketRequest request);

  /// Tickets reported by the logged-in user, newest first.
  Future<List<Ticket>> getMyTickets();

  /// All tickets of one device (Device Overview -> Ticket History), newest first.
  Future<List<Ticket>> getTicketsForDevice(String deviceId);

  /// Throws [NotFoundFailure] if unknown.
  Future<Ticket> getTicketById(String id);
}
