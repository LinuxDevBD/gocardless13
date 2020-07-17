# WARNING: Do not edit by hand, this file was generated by Crank:
#
#   https://github.com/gocardless/crank
#

from . import base_service
from .. import resources
from ..paginator import Paginator
from .. import errors

class MandatesService(base_service.BaseService):
    """Service class that provides access to the mandates
    endpoints of the GoCardless Pro API.
    """

    RESOURCE_CLASS = resources.Mandate
    RESOURCE_NAME = 'mandates'


    def create(self,params=None, headers=None):
        """Create a mandate.

        Creates a new mandate object.

        Args:
              params (dict, optional): Request body.

        Returns:
              ListResponse of Mandate instances
        """
        path = '/mandates'
        
        if params is not None:
            params = {self._envelope_key(): params}

        try:
          response = self._perform_request('POST', path, params, headers,
                                            retry_failures=True)
        except errors.IdempotentCreationConflictError as err:
          return self.get(identity=err.conflicting_resource_id,
                          params=params,
                          headers=headers)
        return self._resource_for(response)
  

    def list(self,params=None, headers=None):
        """List mandates.

        Returns a [cursor-paginated](#api-usage-cursor-pagination) list of your
        mandates.

        Args:
              params (dict, optional): Query string parameters.

        Returns:
              Mandate
        """
        path = '/mandates'
        

        response = self._perform_request('GET', path, params, headers,
                                         retry_failures=True)
        return self._resource_for(response)

    def all(self, params=None):
        if params is None:
            params = {}
        return Paginator(self, params)
    
  

    def get(self,identity,params=None, headers=None):
        """Get a single mandate.

        Retrieves the details of an existing mandate.

        Args:
              identity (string): Unique identifier, beginning with "MD".
              params (dict, optional): Query string parameters.

        Returns:
              ListResponse of Mandate instances
        """
        path = self._sub_url_params('/mandates/:identity', {
          
            'identity': identity,
          })
        

        response = self._perform_request('GET', path, params, headers,
                                         retry_failures=True)
        return self._resource_for(response)
  

    def update(self,identity,params=None, headers=None):
        """Update a mandate.

        Updates a mandate object. This accepts only the metadata parameter.

        Args:
              identity (string): Unique identifier, beginning with "MD".
              params (dict, optional): Request body.

        Returns:
              ListResponse of Mandate instances
        """
        path = self._sub_url_params('/mandates/:identity', {
          
            'identity': identity,
          })
        
        if params is not None:
            params = {self._envelope_key(): params}

        response = self._perform_request('PUT', path, params, headers,
                                         retry_failures=True)
        return self._resource_for(response)
  

    def cancel(self,identity,params=None, headers=None):
        """Cancel a mandate.

        Immediately cancels a mandate and all associated cancellable payments.
        Any metadata supplied to this endpoint will be stored on the mandate
        cancellation event it causes.
        
        This will fail with a `cancellation_failed` error if the mandate is
        already cancelled.

        Args:
              identity (string): Unique identifier, beginning with "MD".
              params (dict, optional): Request body.

        Returns:
              ListResponse of Mandate instances
        """
        path = self._sub_url_params('/mandates/:identity/actions/cancel', {
          
            'identity': identity,
          })
        
        if params is not None:
            params = {'data': params}
        response = self._perform_request('POST', path, params, headers,
                                         retry_failures=False)
        return self._resource_for(response)
  

    def reinstate(self,identity,params=None, headers=None):
        """Reinstate a mandate.

        <a name="mandate_not_inactive"></a>Reinstates a cancelled or expired
        mandate to the banks. You will receive a `resubmission_requested`
        webhook, but after that reinstating the mandate follows the same
        process as its initial creation, so you will receive a `submitted`
        webhook, followed by a `reinstated` or `failed` webhook up to two
        working days later. Any metadata supplied to this endpoint will be
        stored on the `resubmission_requested` event it causes.
        
        This will fail with a `mandate_not_inactive` error if the mandate is
        already being submitted, or is active.
        
        Mandates can be resubmitted up to 3 times.

        Args:
              identity (string): Unique identifier, beginning with "MD".
              params (dict, optional): Request body.

        Returns:
              ListResponse of Mandate instances
        """
        path = self._sub_url_params('/mandates/:identity/actions/reinstate', {
          
            'identity': identity,
          })
        
        if params is not None:
            params = {'data': params}
        response = self._perform_request('POST', path, params, headers,
                                         retry_failures=False)
        return self._resource_for(response)
  
